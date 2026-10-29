# RackHelm FleetOS — systems architecture

## Scope and motivating failure modes

Rack inlet thermal excursions and redundant cooling shortfalls can compound with changes in GPU heat loads, declining fan performance and network issues. RackHelm connects these signals within a single synthetic fleet model and returns explainable, *non-actuating* investigation recommendations.

## Source of truth

SQLite tables are `racks`, `cooling_units`, `power_feeds`, `readings`, `incidents`, `audit`. Rack and unit configuration are immutable in the demo but intended to be provisioned from a trusted equipment inventory in a real deployment. Raw sensor values are stored as validated JSON in `readings`, keyed `(rack_id, observed_at)`; repeated identical payloads do not overwrite data, and conflicting repeats trigger rollback.

All timestamps are UTC normalized, zone IDs and rack IDs match constrained patterns, and ingestion has a bounded payload. Database connections enable WAL, foreign keys and busy timeouts. Atomic batch ingestion acquires a write reservation with `BEGIN IMMEDIATE` to avoid a time-of-check/time-of-use race in the single-node store.

## Risk calculations

1. **Input validation:** reject unknown rack IDs, invalid numeric ranges, NaN/Infinity, naive timestamps, duplicate batch keys and stale/future events outside ingestion policy.
2. **Thermal baseline:** OLS trend over up to 12 recent observations (maximum 55-minute horizon for 5-minute samples); robust modified-z with MAD floor based on recent baseline readings. Long records are bounded.
3. **Equipment evidence:** configured inlet ceiling, rack power headroom, fan RPM, ECC error count, packet-loss percentage, stale samples.
4. **Failure domains:** aggregate current IT rack power by zone; compute modeled N+1 cooling headroom and largest-feed power headroom separately.
5. **Risk fusion:** additive explainable scores, individually capped and globally clamped to [0,100]. `healthy` <35; `warning` >=35; `critical` >=70. The scores rank attention, not probability of failure.
6. **Recommendations:** generate bounded operational triage suggestions. No IPMI, BMC, SNMP SET, Kubernetes eviction, power-cycle or cooling-unit adjustment endpoints exist.
7. **Simulation:** change a hypothetical cooling capacity loss, projected compute loading and inlet setpoint. Estimate temperature using transparent heuristics that must be calibrated against physical equipment.

## API and presentation

FastAPI processes validate inputs, query bounded records and return explainable JSON. The HTML/CSS/JS dashboard requests `/api/v1/overview`, `/api/v1/incidents`, rack history and what-if scenarios; DOM values use `textContent`. A background demo tick advances **only simulated** sensor values every 60 seconds when the app is running in demo mode. No real facility telemetry is collected by default.

`GET /metrics` is authenticated and exports stable, low-cardinality rack/zone gauges. External Prometheus and Grafana are not bundled or connected. `deploy/prometheus.rules.yml` contains reference alert rules that require an independently managed Prometheus installation.

## Sizing and performance

Seed is 48 racks × 36 samples. Current read paths query bounded historical readings per rack, appropriate for a local demo. In a real multi-site fleet, replace this with an indexed time-series service, batching, caching, circuit breakers, backpressure, retention policies, asynchronous fanout and SLO budgets. No synthetic load result is presented as a data-center capacity certification.

## Engineering non-goals

- No unattended physical control or BMS writes.
- No unattended workload draining or Kubernetes rescheduling.
- No predictive-maintenance *supervised ML* model; current predictors are interpretable statistics and uncalibrated heuristics.
- No certified PUE, ASHRAE validation, Tier certification, N+1 certification, energy-savings guarantee or vendor hardware integration.