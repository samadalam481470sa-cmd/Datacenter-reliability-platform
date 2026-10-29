"""Compose inventory, telemetry and risk analytics for API consumption."""

from __future__ import annotations

from datetime import datetime, timezone

from rackhelm import analytics, store


def rack_states(*, at: datetime | None = None) -> tuple[list[dict], list[dict]]:
    racks, cooling, power = store.inventory()
    at = at or datetime.now(timezone.utc)
    states = []
    series = {}
    for rack in racks:
        recent = store.rack_history(rack.rack_id, 48)
        series[rack.rack_id] = recent
        state = rack.model_dump()
        state.update({
            "inlet_c": recent[-1].inlet_c if recent else None,
            "outlet_c": recent[-1].outlet_c if recent else None,
            "power_kw": recent[-1].power_kw if recent else 0.0,
            "gpu_util_pct": recent[-1].gpu_util_pct if recent else 0.0,
            "fan_rpm": recent[-1].fan_rpm if recent else None,
            "packet_loss_pct": recent[-1].packet_loss_pct if recent else None,
            "observed_at": recent[-1].observed_at.isoformat() if recent else None,
        })
        states.append(state)
    zones = analytics.redundancy(states, cooling, power)
    by_zone = {zone["zone"]: zone for zone in zones}
    for rack, state in zip(racks, states, strict=True):
        diagnosis = analytics.diagnostics(
            rack, series[rack.rack_id],
            zone_n1_headroom_kw=by_zone[rack.zone]["cooling_n1_headroom_kw"], at=at,
        )
        state.update(diagnosis)
    return states, zones


def dashboard_state() -> dict:
    states, zones = rack_states()
    kpis = analytics.site_metrics(states)
    open_incidents = store.incidents(limit=500, status="open")
    kpis.update({
        "rack_count": len(states), "zone_count": len(zones),
        "gpu_racks": sum(state["rack_type"] == "GPU" for state in states),
        "open_incidents": len(open_incidents),
        "n1_cooling_zones_at_risk": sum(not z["cooling_n1_pass"] for z in zones),
    })
    return {
        "site": "SYNTHETIC-FACILITY-01", "mode": "synthetic-simulator",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "kpis": kpis, "racks": states, "zones": zones,
        "recommendations": analytics.recommendations(states, zones),
        "advisory_only": True,
    }


def record_incident_candidates() -> int:
    states, zones = rack_states()
    candidates = []
    for r in states:
        if r["severity"] not in ("warning", "critical") or not r["signals"]:
            continue
        strongest = r["signals"][0]
        candidates.append({
            "rack_id": r["rack_id"], "severity": r["severity"],
            "code": strongest["code"], "title": strongest["reason"],
        })
    for zone in zones:
        if not zone["cooling_n1_pass"]:
            candidates.append({"rack_id": zone["zone"], "severity": "warning",
                               "code": "COOLING_REDUNDANCY_LOST",
                               "title": "Modeled largest-unit cooling failover exceeds remaining capacity"})
        if not zone["power_n1_pass"]:
            candidates.append({"rack_id": zone["zone"], "severity": "warning",
                               "code": "POWER_REDUNDANCY_LOST",
                               "title": "Modeled largest-feed failover exceeds remaining capacity"})
    return store.incident_candidates(candidates)


def zone_scenario(zone_id: str, *, cooling_drop_pct: float,
                  gpu_load_delta_pct: float, setpoint_delta_c: float) -> dict:
    _, zones = rack_states()
    zone = next((zone for zone in zones if zone["zone"] == zone_id), None)
    if zone is None:
        raise KeyError(zone_id)
    return analytics.simulate_cooling_loss(
        zone, cooling_drop_pct=cooling_drop_pct,
        gpu_load_delta_pct=gpu_load_delta_pct, setpoint_delta_c=setpoint_delta_c,
    )