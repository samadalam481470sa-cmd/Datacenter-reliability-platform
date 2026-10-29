"""Explainable early-warning rules with temporal and infrastructure-failure models.

NOT an equipment-control algorithm or safety-certified temperature predictor.
Models describe operational risk and must be calibrated per facility before use.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import median

from rackhelm.schemas import CoolingUnit, PowerFeed, Rack, ReadingIn


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def trend_c_per_minute(readings: list[ReadingIn]) -> float:
    """Bounded ordinary least squares on up to the last 12 chronological samples."""
    rows = sorted(readings, key=lambda r: r.observed_at)[-12:]
    if len(rows) < 4:
        return 0.0
    origin = rows[0].observed_at
    xs = [(r.observed_at - origin).total_seconds() / 60 for r in rows]
    if xs[-1] - xs[0] < 5:
        return 0.0
    ys = [r.inlet_c for r in rows]
    xm = sum(xs) / len(xs)
    ym = sum(ys) / len(ys)
    denom = sum((x - xm) ** 2 for x in xs)
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys, strict=True)) / denom if denom else 0.0


def robust_temperature_anomaly(readings: list[ReadingIn]) -> float:
    """Positive-only robust modified z-score relative to prior readings."""
    rows = sorted(readings, key=lambda r: r.observed_at)
    if len(rows) < 9:
        return 0.0
    previous = [r.inlet_c for r in rows[:-1]][-24:]
    center = median(previous)
    deviation = median(abs(x - center) for x in previous)
    # Use engineering noise floor to prevent constant sensors creating false infinity.
    return max(0.0, .6745 * (rows[-1].inlet_c - center) / max(deviation, .28))


def redundancy(racks: list[dict], cooling: list[CoolingUnit],
               power: list[PowerFeed]) -> list[dict]:
    """N+1 failure capacity check; no assumption that electrical and cooling kW are interchangeable.

    Cooling capacity_kw is explicitly configured here as a synthetic heat-removal
    kW equivalent, while power feed capacity_kw is electrical supply kW.
    """
    rack_groups: dict[str, list[dict]] = defaultdict(list)
    for rack in racks:
        rack_groups[rack["zone"]].append(rack)
    zones = []
    for zone, group in sorted(rack_groups.items()):
        active_kw = sum(float(r.get("power_kw") or 0) for r in group)
        cool = [c.capacity_kw * c.availability if c.state != "offline" else 0
                for c in cooling if c.zone == zone]
        elec = [p.capacity_kw if p.state == "online" else 0 for p in power if p.zone == zone]
        # One entire largest unit/feed fails. Remaining combined capacity must cover IT.
        cool_n1 = sum(cool) - max(cool, default=0)
        elec_n1 = sum(elec) - max(elec, default=0)
        cool_current = sum(cool)
        elec_current = sum(elec)
        zones.append({
            "zone": zone,
            "rack_count": len(group),
            "it_kw": round(active_kw, 2),
            "cooling_capacity_kw": round(cool_current, 2),
            "cooling_n1_headroom_kw": round(cool_n1 - active_kw, 2),
            "power_capacity_kw": round(elec_current, 2),
            "power_n1_headroom_kw": round(elec_n1 - active_kw, 2),
            "cooling_n1_pass": cool_n1 >= active_kw,
            "power_n1_pass": elec_n1 >= active_kw,
            "peak_inlet_c": round(max((r.get("inlet_c") or 0 for r in group), default=0), 2),
        })
    return zones


def diagnostics(rack: Rack, readings: list[ReadingIn], *,
                zone_n1_headroom_kw: float = 100,
                at: datetime | None = None) -> dict:
    if not readings:
        return {"rack_id": rack.rack_id, "risk": 100, "severity": "unknown",
                "signals": [{"code": "NO_TELEMETRY", "weight": 100,
                             "reason": "No sensor records received"}],
                "eta_to_limit_minutes": None, "warming_c_per_hour": 0,
                "confidence": "no-data"}
    records = sorted(readings, key=lambda r: r.observed_at)
    current = records[-1]
    now = at or datetime.now(timezone.utc)
    age_minutes = max(0, (now - current.observed_at).total_seconds() / 60)
    slope = trend_c_per_minute(records)
    anomaly = robust_temperature_anomaly(records)
    headroom = rack.temp_limit_c - current.inlet_c
    signals: list[dict] = []

    def signal(code: str, weight: float, reason: str) -> None:
        if weight >= 0.8:
            signals.append({"code": code, "weight": round(weight, 1), "reason": reason})

    if headroom <= 0:
        signal("INLET_CEILING_EXCEEDED", 48, "Rack inlet exceeds the configured advisory limit")
    elif headroom < 4:
        signal("THERMAL_HEADROOM_LOW", 34 * (4 - headroom) / 4,
               f"Only {headroom:.1f} °C below this rack's configured limit")
    if slope > 0.013:
        signal("SUSTAINED_WARMING", min(23, slope * 60 * 2.7),
               f"Inlet is warming at {slope * 60:.2f} °C/hour")
    if anomaly >= 3.5:
        signal("ROBUST_TEMPERATURE_ANOMALY", min(16, anomaly * 2.1),
               f"Temperature differs from historical median (modified z={anomaly:.1f})")
    ratio = current.power_kw / rack.max_kw
    if ratio >= 0.80:
        signal("POWER_HEADROOM_LOW", min(24, (ratio - .78) * 100),
               f"Rack draws {ratio * 100:.0f}% of configured electrical budget")
    if current.fan_rpm < 3300:
        signal("FAN_SPEED_LOW", 16, "Fan telemetry below configured demo threshold")
    if current.ecc_errors > 0:
        signal("ECC_ERROR_ACTIVITY", min(18, current.ecc_errors * 5),
               "Correctable or uncorrectable GPU ECC count requires investigation")
    if current.packet_loss_pct >= .25:
        signal("NETWORK_PACKET_LOSS", min(20, current.packet_loss_pct * 7),
               f"Observed packet loss is {current.packet_loss_pct:.2f}%")
    if zone_n1_headroom_kw < 0:
        signal("COOLING_N_PLUS_ONE_DEFICIT", min(15, 5 + abs(zone_n1_headroom_kw) / 8),
               "Zone cannot meet the modeled IT load after losing its largest cooling unit")
    if age_minutes > 10:
        signal("STALE_SENSOR", min(24, 10 + age_minutes),
               f"Sensor has not reported for {age_minutes:.0f} minutes")
    risk = round(min(100.0, sum(s["weight"] for s in signals)), 1)
    severity = "critical" if risk >= 70 else "warning" if risk >= 35 else "healthy"
    eta = None
    if slope > .015 and headroom > 0:
        eta = round(_clamp(headroom / slope, 0, 10080), 1)
    elif headroom <= 0:
        eta = 0.0
    return {
        "rack_id": rack.rack_id, "risk": risk, "severity": severity,
        "signals": sorted(signals, key=lambda s: (-s["weight"], s["code"])),
        "warming_c_per_hour": round(slope * 60, 3),
        "robust_temp_z": round(anomaly, 2),
        "headroom_c": round(headroom, 2),
        "eta_to_limit_minutes": eta,
        "confidence": "medium" if len(records) >= 12 and age_minutes <= 10 else "low",
        "freshness_minutes": round(age_minutes, 1),
        "sample_count": len(records),
    }


def recommendations(rack_states: list[dict], zones: list[dict]) -> list[dict]:
    actions = []
    for rack in sorted(rack_states, key=lambda r: -r["risk"]):
        if rack["risk"] < 25:
            continue
        hints = {s["code"] for s in rack["signals"]}
        if "FAN_SPEED_LOW" in hints or "SUSTAINED_WARMING" in hints:
            rec = "Inspect fans, airflow containment and blanking panels; check cooling supply"
        elif "NETWORK_PACKET_LOSS" in hints:
            rec = "Check NIC error counters, cable/optic health and top-of-rack switch"
        elif "POWER_HEADROOM_LOW" in hints:
            rec = "Review power telemetry and schedule workload migration after approval"
        else:
            rec = "Verify sensor readings and check rack operating conditions"
        actions.append({"rack_id": rack["rack_id"], "priority": rack["severity"],
                        "risk": rack["risk"], "action": rec, "mode": "advisory_only"})
    for zone in zones:
        if not zone["cooling_n1_pass"]:
            actions.append({"rack_id": zone["zone"], "priority": "warning",
                            "risk": 65, "action": "Assess cooling N+1 redundancy and verify failover plan",
                            "mode": "advisory_only"})
    return actions[:12]


def simulate_cooling_loss(zone: dict, *, cooling_drop_pct: float = 0,
                          gpu_load_delta_pct: float = 0, setpoint_delta_c: float = 0) -> dict:
    """Transparent planning heuristic, NOT calibrated CFD or physical protection control."""
    baseline_kw = float(zone["it_kw"])
    projected_kw = baseline_kw * (1 + gpu_load_delta_pct / 100)
    available_capacity = zone["cooling_capacity_kw"] * (1 - cooling_drop_pct / 100)
    # Projected cooling capacity uses configured thermal equivalent, not electrical draw.
    capacity_gap = max(0, projected_kw - available_capacity)
    temp_increase = (gpu_load_delta_pct / 100) * 3.2 + cooling_drop_pct / 100 * 6.5
    temp_increase += (capacity_gap / max(projected_kw, 1)) * 6
    predicted_peak = zone["peak_inlet_c"] + temp_increase + setpoint_delta_c
    likely_over = max(0, predicted_peak - 27)
    risk = min(100, 20 + 19 * likely_over + 35 * capacity_gap / max(projected_kw, 1))
    return {
        "zone": zone["zone"], "baseline_it_kw": round(baseline_kw, 2),
        "scenario_it_kw": round(projected_kw, 2),
        "cooling_remaining_kw": round(available_capacity, 2),
        "capacity_gap_kw": round(capacity_gap, 2),
        "estimated_peak_inlet_c": round(predicted_peak, 2),
        "thermal_risk_index": round(risk, 1),
        "would_exceed_demo_limit": predicted_peak >= 27,
        "control_actions_executed": False,
        "qualification": "Planning heuristic; requires site-specific calibration and engineering review",
    }


def site_metrics(rack_states: list[dict]) -> dict:
    total_kw = sum(r.get("power_kw") or 0 for r in rack_states)
    gpu_kw = sum(r.get("power_kw") or 0 for r in rack_states if r["rack_type"] == "GPU")
    # COP=3.5 is a synthetic assumption for an illustrative estimate.
    cooling_kw = total_kw / 3.5
    other_kw = 12 + 0.025 * total_kw
    facility_kw = total_kw + cooling_kw + other_kw
    return {
        "it_load_kw": round(total_kw, 2),
        "gpu_load_kw": round(gpu_kw, 2),
        "estimated_facility_kw": round(facility_kw, 2),
        "estimated_pue": round(facility_kw / total_kw, 3) if total_kw else None,
        "pue_quality": "simulated-not-metered",
        "cooling_kw_estimate": round(cooling_kw, 2),
        "affected_racks": sum(r["severity"] != "healthy" for r in rack_states),
        "critical_racks": sum(r["severity"] == "critical" for r in rack_states),
    }