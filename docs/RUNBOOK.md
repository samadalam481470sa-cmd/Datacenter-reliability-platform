# RackHelm operations runbook

## Local boot

Install Python 3.11+ and run `python -m pip install -e ".[dev]"`. Then start with `uvicorn rackhelm.api:app --host 127.0.0.1 --port 8000`; visit `/`, `/docs`, and run `python scripts/smoke.py`. To use Docker, run `docker compose up --build -d` then `docker compose logs -f`.

## Operator telemetry

For a private collector deployment, configure `RACKHELM_MODE=secure` and an absolute persistent database location; in local synthetic demo mode, enabling telemetry writes requires `RACKHELM_ALLOW_DEMO_INGEST=1` and all reads remain public. Never send real customer data to the demo. Use an independent authenticated source that normalizes readings to the `ReadingIn` schema. You can test ingestion with `scripts/import_jsonl.py`; it uses a private `RACKHELM_OPERATOR_KEY` and enforces HTTPS for remote endpoints. Network and physical instrumentation must be separately commissioned and authorized. An alert must be physically verified before a change to fan settings, cooling or workload placement.

## Triage procedure

1. Identify critical/warning racks in the map; select a rack to see actual time-series slope, headroom, and diagnostic signals.
2. Check whether the temperature signal is fresh, whether fan RPM is plausible, and whether neighbor/aisle physical issues exist.
3. Check electrical and cooling N+1 headroom. A negative headroom indicates modeled *failure tolerance* deficiency; it does not automatically mean current cooling is insufficient.
4. Run a **planning-only** cooling-loss simulation. Discuss its assumptions and compare results with physical metering, facility diagrams and engineering design specifications.
5. Record an incident acknowledgement with an operator ID and meaningful note. Escalate to the electrical/mechanical/IT on-call owner as appropriate. Any actual changes require established change control.
6. Resolve only after telemetry recovery and operator confirmation.

## Backup and recovery

The demo uses SQLite WAL. Backup must use the SQLite online backup API or a quiesced database snapshot including WAL, not an unsynchronized copy of a busy file. An operator should test restore of telemetry, incidents and audit events in a separate environment. No automated backup or recovery rehearsal is included. A real deployment needs encrypted off-site copies, recovery-point objectives, and retention/deletion policies.

## Monitoring

`GET /metrics` requires the operator key. Configure Prometheus HTTP scrape authentication using a private header through your trusted gateway. Import and tune `deploy/prometheus.rules.yml` and wire alerts into Alertmanager/on-call. The provided rules are examples; no Prometheus/Grafana instance is started by this project. Do not expose private credentials in Grafana panels or dashboards.

## Common problems

| Symptom | Investigate |
|---|---|
| `/health` returns 503 | Disk writable, database permissions, container logs |
| `/api/v1/overview` returns 503 | Secure mode missing valid `RACKHELM_OPERATOR_KEY` |
| `POST /telemetry/batch` 409 | Conflicting duplicate sample, unexpected rack, or timestamp outside freshness policy |
| Many stale sensors | Check collector deployment and time synchronization; demo process may be stopped |
| Unexpected N+1 alarms | Validate actual cooling heat-removal units, cooling state, redundancy boundaries and facility metadata |
| PUE seems wrong | It is an assumption-based demo estimate, not facility meter data |
| Thermal ETA seems too aggressive | Compare to physical sensor drift, temperature sensor calibration and regression noise |

## No-autonomy guardrail

RackHelm deliberately lacks code paths to execute UPS/PDU switching, cooling-system setpoint changes, fan controls, GPU workload eviction or server restarts. These would be inappropriate without site-specific engineering assurance, authorization and safety controls.