"""FastAPI server for the synthetic digital twin and restricted operator telemetry."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from rackhelm import __version__, service, store
from rackhelm.observability import metrics_text
from rackhelm.schemas import BatchIn, IncidentAction

_WEB_DIR = Path(__file__).with_name("web")
_LOG = logging.getLogger("rackhelm.api")

# Bounds on what an unauthenticated peer can make this process accept or do.
# Pydantic already bounds the *number* of readings; this bounds the raw bytes.
_MAX_BODY_BYTES = int(os.environ.get("RACKHELM_MAX_BODY_BYTES", "1000000"))
_RATE_LIMIT_PER_MINUTE = int(os.environ.get("RACKHELM_RATE_LIMIT_PER_MINUTE", "600"))
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_UNMETERED_PATHS = frozenset({"/health"})


class _RateLimiter:
    """Bounded per-process fixed-window limiter keyed by peer address.

    This raises the cost of credential stuffing, scraping and runaway polling on
    a single instance. It is not a distributed limiter: once several replicas
    serve traffic, enforce limits at the edge proxy or WAF instead.

    The peer address is used deliberately instead of ``X-Forwarded-For``, which
    a client can forge to escape its own bucket. If a trusted proxy terminates
    TLS, run Uvicorn with ``--proxy-headers`` and a restricted
    ``--forwarded-allow-ips`` list so the address is rewritten before it arrives.
    """

    _MAX_CLIENTS = 4096

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = limit_per_minute
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, int]] = {}

    def allow(self, client: str) -> bool:
        if self.limit <= 0:
            return True
        minute = int(time.monotonic() // 60)
        with self._lock:
            seen_minute, count = self._windows.get(client, (minute, 0))
            if seen_minute != minute:
                count = 0
            count += 1
            if client not in self._windows and len(self._windows) >= self._MAX_CLIENTS:
                for stale in [key for key, (m, _) in self._windows.items() if m != minute]:
                    del self._windows[stale]
                if len(self._windows) >= self._MAX_CLIENTS:
                    # Fail closed rather than let the table grow without bound.
                    return False
            self._windows[client] = (minute, count)
            return count <= self.limit


_limiter = _RateLimiter(_RATE_LIMIT_PER_MINUTE)


def _operator_key() -> str:
    key = os.environ.get("RACKHELM_OPERATOR_KEY", "")
    if len(key) < 32 or len(set(key)) < 6:
        raise HTTPException(status_code=503, detail="Operator authentication not configured")
    return key


def require_operator(x_api_key: str | None = Header(default=None)) -> None:
    key = _operator_key()
    if not secrets.compare_digest(x_api_key or "", key):
        raise HTTPException(status_code=401, detail="Invalid operator credentials")


def read_guard(x_api_key: str | None = Header(default=None)) -> None:
    if os.getenv("RACKHELM_MODE", "demo") != "demo":
        require_operator(x_api_key)


async def _demo_clock() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            count = await asyncio.to_thread(store.advance_synthetic_demo)
            if count:
                await asyncio.to_thread(service.record_incident_candidates)
        except Exception:
            logging.getLogger("rackhelm.simulator").exception("Synthetic demo tick failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.initialize()
    task = asyncio.create_task(_demo_clock()) if os.getenv("RACKHELM_MODE", "demo") == "demo" else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="RackHelm FleetOS", version=__version__,
    description="Explainable data-center fleet reliability and digital twin simulator",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv("RACKHELM_MODE", "demo") != "secure" else None,
)
app.mount("/assets", StaticFiles(directory=_WEB_DIR), name="assets")


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    """Log the traceback server-side and never return internals to the caller."""
    _LOG.error("Unhandled request error", exc_info=exc)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.middleware("http")
async def secure_response_headers(request: Request, call_next):
    peer = request.client.host if request.client else "unknown"
    if request.url.path not in _UNMETERED_PATHS and not _limiter.allow(peer):
        return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429,
                            headers={"Retry-After": "60"})
    if request.method in _WRITE_METHODS:
        # A chunked body declares no length, so it could stream past the cap.
        # Demand an explicit length and refuse the request when it is missing.
        declared = request.headers.get("content-length", "")
        if "chunked" in request.headers.get("transfer-encoding", "").lower() or not declared.isdigit():
            return JSONResponse({"detail": "Content-Length required for write requests"},
                                status_code=411)
        if int(declared) > _MAX_BODY_BYTES:
            return JSONResponse({"detail": "Request too large"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )
    # Ignored on plain HTTP; effective once a TLS terminator fronts the service.
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "form-action 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    return response


@app.get("/", include_in_schema=False)
def index():
    if os.getenv("RACKHELM_MODE", "demo") != "demo":
        raise HTTPException(status_code=404, detail="Use authenticated API endpoints")
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/health")
def health():
    try:
        with store.connection() as db:
            db.execute("SELECT 1").fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "version": __version__}


@app.get("/api/v1/overview", dependencies=[Depends(read_guard)])
def overview():
    return service.dashboard_state()


@app.get("/api/v1/racks", dependencies=[Depends(read_guard)])
def racks(zone: str | None = Query(default=None, pattern=r"^Z0[1-4]$")):
    states, _ = service.rack_states()
    return {"racks": [r for r in states if zone is None or r["zone"] == zone]}


@app.get("/api/v1/racks/{rack_id}/history", dependencies=[Depends(read_guard)])
def rack_history(rack_id: str, limit: int = Query(default=36, ge=2, le=200)):
    racks, _, _ = store.inventory()
    if rack_id not in {r.rack_id for r in racks}:
        raise HTTPException(status_code=404, detail="Unknown rack")
    readings = store.rack_history(rack_id, limit)
    return {"rack_id": rack_id, "readings": [r.model_dump(mode="json") for r in readings]}


@app.get("/api/v1/racks/{rack_id}/diagnostics", dependencies=[Depends(read_guard)])
def rack_diagnostics(rack_id: str):
    states, _ = service.rack_states()
    rack = next((r for r in states if r["rack_id"] == rack_id), None)
    if rack is None:
        raise HTTPException(status_code=404, detail="Unknown rack")
    return rack


@app.get("/api/v1/incidents", dependencies=[Depends(read_guard)])
def incidents(status: str | None = Query(default=None, pattern=r"^(open|acknowledged|resolved)$"),
              limit: int = Query(default=100, ge=1, le=200)):
    return {"incidents": store.incidents(limit=limit, status=status)}


@app.get("/api/v1/scenario", dependencies=[Depends(read_guard)])
def scenario(zone: str = Query(default="Z02", pattern=r"^Z0[1-4]$"),
             cooling_drop_pct: float = Query(default=30, ge=0, le=100),
             gpu_load_delta_pct: float = Query(default=15, ge=-30, le=60),
             setpoint_delta_c: float = Query(default=0, ge=-5, le=6)):
    try:
        return service.zone_scenario(
            zone, cooling_drop_pct=cooling_drop_pct,
            gpu_load_delta_pct=gpu_load_delta_pct, setpoint_delta_c=setpoint_delta_c,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Unknown zone") from exc


@app.get("/metrics", include_in_schema=False, dependencies=[Depends(require_operator)])
def prometheus_metrics():
    return PlainTextResponse(metrics_text(), media_type="text/plain; version=0.0.4")


@app.get("/api/v1/audit/verify", dependencies=[Depends(require_operator)])
def verify_audit():
    return store.audit_valid()


@app.post("/api/v1/telemetry/batch", dependencies=[Depends(require_operator)])
def ingest(payload: BatchIn):
    # Public synthetic demo must not accidentally publish private telemetry.
    # Any local demo write needs an explicit opt-in; secure deployments protect reads.
    if (os.getenv("RACKHELM_MODE", "demo") == "demo"
            and os.getenv("RACKHELM_ALLOW_DEMO_INGEST", "0") != "1"):
        raise HTTPException(status_code=403, detail="Demo data ingestion disabled by default")
    try:
        inserted = store.ingest_batch(payload.readings)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    opened = service.record_incident_candidates() if inserted else 0
    return {"accepted": len(payload.readings), "inserted": inserted,
            "duplicate": len(payload.readings) - inserted, "new_incidents": opened}


@app.post("/api/v1/incidents/{incident_id}/status", dependencies=[Depends(require_operator)])
def incident_action(incident_id: str, payload: IncidentAction):
    try:
        result = store.update_incident(incident_id, payload.status, payload.note, payload.operator)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Unknown incident")
    return result
