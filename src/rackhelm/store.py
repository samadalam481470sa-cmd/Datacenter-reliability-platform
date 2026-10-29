"""SQLite-backed site inventory, immutable time-series, incidents, and audit chain."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from math import sin
from pathlib import Path

from rackhelm.demo import facility_model, synthetic_readings
from rackhelm.schemas import CoolingUnit, PowerFeed, Rack, ReadingIn

_INIT_LOCK = threading.Lock()


def db_path() -> str:
    return os.environ.get("RACKHELM_DB_PATH", "/tmp/rackhelm.db")


@contextmanager
def connection():
    path = db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 15000")
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    """Create safe synthetic demo data once. No production hardware interaction."""
    mode = os.environ.get("RACKHELM_MODE", "demo")
    if mode not in ("demo", "secure"):
        raise RuntimeError("Unknown RACKHELM_MODE: refusing to expose data")
    if mode == "secure" and (
        len(os.environ.get("RACKHELM_OPERATOR_KEY", "")) < 32
        or db_path() in ("", ":memory:")
        or not Path(db_path()).is_absolute()
        or db_path().startswith("/tmp/")
    ):
        raise RuntimeError("Secure mode requires an operator secret and persistent absolute database path")
    with _INIT_LOCK, connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS racks (
          rack_id TEXT PRIMARY KEY, zone TEXT NOT NULL, body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cooling_units (
          unit_id TEXT PRIMARY KEY, zone TEXT NOT NULL, body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS power_feeds (
          feed_id TEXT PRIMARY KEY, zone TEXT NOT NULL, body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS readings (
          rack_id TEXT NOT NULL REFERENCES racks(rack_id),
          observed_at TEXT NOT NULL, body TEXT NOT NULL,
          PRIMARY KEY (rack_id, observed_at)
        );
        CREATE INDEX IF NOT EXISTS readings_time_idx ON readings(observed_at);
        CREATE TABLE IF NOT EXISTS incidents (
          incident_id TEXT PRIMARY KEY, rack_id TEXT NOT NULL,
          severity TEXT NOT NULL, code TEXT NOT NULL,
          title TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL,
          subject TEXT NOT NULL, detail TEXT NOT NULL,
          previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL
        );
        """)
        row = db.execute("SELECT COUNT(*) AS n FROM racks").fetchone()
        if row["n"]:
            return
        racks, cooling, power = facility_model()
        db.executemany("INSERT INTO racks VALUES (?,?,?)", [(r.rack_id, r.zone, r.model_dump_json()) for r in racks])
        db.executemany("INSERT INTO cooling_units VALUES (?,?,?)", [(c.unit_id, c.zone, c.model_dump_json()) for c in cooling])
        db.executemany("INSERT INTO power_feeds VALUES (?,?,?)", [(p.feed_id, p.zone, p.model_dump_json()) for p in power])
        if mode == "demo":
            demo = synthetic_readings(racks)
            db.executemany("INSERT INTO readings VALUES (?,?,?)", [
                (r.rack_id, r.observed_at.isoformat(), r.model_dump_json()) for r in demo
            ])
        _audit(db, "bootstrap", "inventory_seeded", "facility", {"rack_count": len(racks)})
    if mode == "demo":
        from rackhelm.service import record_incident_candidates

        record_incident_candidates()


def _audit(db: sqlite3.Connection, actor: str, kind: str, subject: str, detail: dict) -> None:
    previous = db.execute("SELECT event_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    prev = previous["event_hash"] if previous else "0" * 64
    timestamp = datetime.now(timezone.utc).isoformat()
    body = json.dumps(detail, sort_keys=True, separators=(",", ":"))
    canonical = json.dumps([prev, timestamp, actor, kind, subject, body], separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    db.execute("INSERT INTO audit(timestamp,actor,kind,subject,detail,previous_hash,event_hash) "
               "VALUES(?,?,?,?,?,?,?)", (timestamp, actor, kind, subject, body, prev, digest))


def audit_valid() -> dict:
    with connection() as db:
        rows = db.execute("SELECT * FROM audit ORDER BY id ASC").fetchall()
    prev = "0" * 64
    for row in rows:
        canonical = json.dumps([prev, row["timestamp"], row["actor"], row["kind"], row["subject"],
                                row["detail"]], separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        if not hmac.compare_digest(digest, row["event_hash"]) or row["previous_hash"] != prev:
            return {"valid": False, "events_checked": row["id"]}
        prev = digest
    return {"valid": True, "events_checked": len(rows), "head_hash": prev}


def inventory() -> tuple[list[Rack], list[CoolingUnit], list[PowerFeed]]:
    with connection() as db:
        racks = db.execute("SELECT body FROM racks ORDER BY rack_id").fetchall()
        cool = db.execute("SELECT body FROM cooling_units ORDER BY unit_id").fetchall()
        feeds = db.execute("SELECT body FROM power_feeds ORDER BY feed_id").fetchall()
    return ([Rack.model_validate_json(row["body"]) for row in racks],
            [CoolingUnit.model_validate_json(row["body"]) for row in cool],
            [PowerFeed.model_validate_json(row["body"]) for row in feeds])


def rack_history(rack_id: str, limit: int = 48) -> list[ReadingIn]:
    with connection() as db:
        rows = db.execute(
            "SELECT body FROM readings WHERE rack_id = ? ORDER BY observed_at DESC LIMIT ?",
            (rack_id, limit),
        ).fetchall()
    return [ReadingIn.model_validate_json(row["body"]) for row in reversed(rows)]


def ingest_batch(readings: list[ReadingIn]) -> int:
    """Atomic, strictly idempotent write. Duplicate differing payloads fail the full batch."""
    now = datetime.now(timezone.utc)
    if any(r.observed_at > now + timedelta(minutes=5) or
           r.observed_at < now - timedelta(days=7) for r in readings):
        raise ValueError("Readings must be within the last seven days, or five minutes ahead")
    keys = [(r.rack_id, r.observed_at.isoformat()) for r in readings]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate rack/time keys within ingestion batch")
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        known = {row["rack_id"] for row in db.execute("SELECT rack_id FROM racks")}
        if any(r.rack_id not in known for r in readings):
            raise ValueError("Unknown rack in telemetry payload")
        inserted = 0
        for r in readings:
            body = r.model_dump_json()
            prior = db.execute("SELECT body FROM readings WHERE rack_id=? AND observed_at=?",
                               (r.rack_id, r.observed_at.isoformat())).fetchone()
            if prior:
                if not hmac.compare_digest(prior["body"], body):
                    raise ValueError("Telemetry conflict: same rack/time, different values")
                continue
            db.execute("INSERT INTO readings VALUES (?,?,?)",
                       (r.rack_id, r.observed_at.isoformat(), body))
            inserted += 1
        _audit(db, "api_ingestor", "telemetry_batch", "rack_fleet",
               {"submitted": len(readings), "inserted": inserted})
    return inserted


def incident_candidates(entries: list[dict]) -> int:
    """Open each new candidate once; retain user acknowledgements and resolutions."""
    if not entries:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    opened = 0
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        for item in entries:
            incident_id = f"{item['rack_id']}:{item['code']}"
            cur = db.execute("INSERT OR IGNORE INTO incidents VALUES (?,?,?,?,?,?,?,?,?)",
                             (incident_id, item["rack_id"], item["severity"], item["code"],
                              item["title"], "open", now, now, ""))
            if cur.rowcount:
                opened += 1
                _audit(db, "risk_engine", "incident_opened", incident_id,
                       {"severity": item["severity"], "code": item["code"]})
    return opened


def incidents(limit: int = 100, status: str | None = None) -> list[dict]:
    with connection() as db:
        if status is None:
            rows = db.execute("SELECT * FROM incidents ORDER BY updated_at DESC, incident_id LIMIT ?",
                              (limit,)).fetchall()
        else:
            rows = db.execute("SELECT * FROM incidents WHERE status=? "
                              "ORDER BY updated_at DESC, incident_id LIMIT ?", (status, limit)).fetchall()
    return [dict(row) for row in rows]


def update_incident(incident_id: str, status: str, note: str, operator: str) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        previous = db.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if previous is None:
            return None
        if previous["status"] == "resolved" and status != "resolved":
            raise ValueError("Resolved incident cannot be reopened through acknowledgement")
        db.execute("UPDATE incidents SET status=?,note=?,updated_at=? WHERE incident_id=?",
                   (status, note, now, incident_id))
        _audit(db, operator, "incident_status_changed", incident_id,
               {"before": previous["status"], "after": status, "note": note})
        result = db.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        return dict(result)


def advance_synthetic_demo(*, at: datetime | None = None) -> int:
    """Append exactly one realistic-ish synthetic sample per rack on a new clock minute.

    No physical sensor queries, remote systems, or actuator commands are executed.
    This maintains a fresh browser demo during an extended recruiter session.
    """
    if os.environ.get("RACKHELM_MODE", "demo") != "demo":
        return 0
    now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    racks, _, _ = inventory()
    generated = synthetic_readings(racks, now=now, points=36)[-len(racks):]
    phase = int(now.timestamp() // 60)
    updates = []
    for index, reading in enumerate(generated):
        drift = 0.25 * sin(phase / 9 + index / 6)
        updates.append(reading.model_copy(update={
            "inlet_c": round(reading.inlet_c + drift, 3),
            "outlet_c": round(reading.outlet_c + drift, 3),
        }))
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        last = db.execute("SELECT MAX(observed_at) AS latest FROM readings").fetchone()["latest"]
        if last and datetime.fromisoformat(last) >= now:
            return 0
        db.executemany("INSERT INTO readings VALUES (?,?,?)", [
            (r.rack_id, r.observed_at.isoformat(), r.model_dump_json()) for r in updates
        ])
        _audit(db, "synthetic_simulator", "demo_tick", "facility", {"samples": len(updates)})
    return len(updates)