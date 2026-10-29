from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from rackhelm import store
from rackhelm.schemas import ReadingIn


def sample(time=None, **changes):
    data = {
        "rack_id": "Z02-R04", "observed_at": time or datetime.now(timezone.utc),
        "inlet_c":25.3, "outlet_c":37.2, "power_kw":14,
        "gpu_util_pct":80,"fan_rpm":2500,"ecc_errors":0,"packet_loss_pct":0.02,
    }
    data.update(changes)
    return ReadingIn(**data)


def test_atomic_ingest_and_idempotency(site):
    now = datetime.now(timezone.utc).replace(microsecond=314159)
    first = sample(now)
    assert store.ingest_batch([first]) == 1
    assert store.ingest_batch([first]) == 0
    current = store.rack_history("Z02-R04",1)[-1]
    assert current.observed_at == first.observed_at


def test_immutable_conflict_rejected(site):
    now = datetime.now(timezone.utc).replace(microsecond=314159)
    first = sample(now)
    store.ingest_batch([first])
    with pytest.raises(ValueError,match="conflict"):
        store.ingest_batch([sample(now,inlet_c=40)])
    assert store.rack_history("Z02-R04",1)[-1].inlet_c == first.inlet_c


def test_atomic_batch_rolls_back_on_conflict(site):
    now = datetime.now(timezone.utc).replace(microsecond=314159)
    store.ingest_batch([sample(now)])
    new = sample(now + timedelta(seconds=3), rack_id="Z01-R01")
    with pytest.raises(ValueError,match="conflict"):
        store.ingest_batch([new, sample(now,inlet_c=40)])
    assert not any(r.observed_at == new.observed_at for r in store.rack_history("Z01-R01",10))


def test_duplicate_in_batch_rejected(site):
    r=sample()
    with pytest.raises(ValueError,match="Duplicate"):
        store.ingest_batch([r,r])


def test_unknown_rack_rejected(site):
    with pytest.raises(ValueError,match="Unknown rack"):
        store.ingest_batch([sample(rack_id="Z99-R99")])


def test_old_or_future_telemetry_rejected(site):
    with pytest.raises(ValueError,match="last seven"):
        store.ingest_batch([sample(datetime.now(timezone.utc) - timedelta(days=8))])
    with pytest.raises(ValueError,match="last seven"):
        store.ingest_batch([sample(datetime.now(timezone.utc) + timedelta(minutes=30))])


def test_audit_chain_valid_and_detects_tampering(site):
    before=store.audit_valid()
    assert before["valid"] and before["events_checked"]>0
    with store.connection() as db:
        db.execute("UPDATE audit SET detail='{}' WHERE id=(SELECT min(id) FROM audit)")
    assert store.audit_valid()["valid"] is False


def test_operator_updates_audited(site):
    current=store.incidents(limit=5)[0]
    updated=store.update_incident(current["incident_id"],"acknowledged","Checked rack fans","operator-1")
    assert updated["status"]=="acknowledged"
    assert updated["note"]=="Checked rack fans"
    assert store.audit_valid()["valid"]
    store.update_incident(current["incident_id"],"resolved","Fan replaced and telemetry verified","operator-1")
    with pytest.raises(ValueError,match="Resolved"):
        store.update_incident(current["incident_id"],"acknowledged","Attempt reopen","operator-1")


def test_missing_incident_is_none(site):
    assert store.update_incident("missing","resolved","No such item","operator") is None


def test_synthetic_clock_appends_once_per_minute_and_audits(site):
    previous=store.audit_valid()["events_checked"]
    future=datetime.now(timezone.utc)+timedelta(minutes=2)
    assert store.advance_synthetic_demo(at=future)==48
    assert store.advance_synthetic_demo(at=future)==0
    assert store.audit_valid()["valid"]
    assert store.audit_valid()["events_checked"]==previous+1


def test_secure_mode_never_advances_synthetic_clock(site,monkeypatch):
    monkeypatch.setenv("RACKHELM_MODE","secure")
    assert store.advance_synthetic_demo()==0


def test_unknown_run_mode_fails_closed(tmp_path,monkeypatch):
    monkeypatch.setenv("RACKHELM_DB_PATH",str(tmp_path/"unknown.db"))
    monkeypatch.setenv("RACKHELM_MODE","accidental-public")
    with pytest.raises(RuntimeError,match="Unknown"):
        store.initialize()