# Independent engineering validation protocol (not yet performed)

**Current state:** tests prove software behavior on *synthetic* conditions; this project has never been independently validated on a real data center. Risk scores are not probabilistic, ETA is an extrapolation, and scenario models are uncalibrated heuristics.

## Minimum acceptance protocol for a real site

- Obtain written approval and lawful access to site sensor readings; preserve original sensor provenance, clocks, physical calibration and known maintenance windows.
- Freeze site-specific rack inlet operating limits and verify server manufacturer, workload, altitude and cooling design constraints.
- Replay real readings in chronological order and blind-hold-out real incidents. Separate tuning/calibration from validation to avoid leakage.
- Compare baselines: static limit alert, slope-only alert, anomaly-only alert, combined risk fusion, and a separately validated third-party DCIM monitoring baseline.
- Report detection delay, precision/recall of actionable incidents, false pages per rack-day, calibration of physical trend forecasts, P50/P95 API latency and error/coverage rates; include confidence intervals.
- Stress test missing sensors, late/out-of-order readings, clock skew, bursty telemetry, hot-spare failover, failing CRACs, GPU load spikes, power-path derating and nonindependent units sharing downstream dependencies.
- Test N+1 calculations against electrical single-line diagrams and cooling mechanical drawings; simple kW summation cannot certify actual Tier, redundancy or thermodynamic behavior.
- Review runbooks with on-call electricians, mechanical engineers and fleet technicians before field use. All automatic physical controls remain disabled.

## Scope notes

The application reports an estimated PUE assuming synthetic COP and overhead, not an actual power/energy metering method. The thermal projection applies a deliberately transparent, physically simplified coefficient model and must not be used for environmental control or emergency decisions.