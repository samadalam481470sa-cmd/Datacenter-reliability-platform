from __future__ import annotations

from datetime import datetime, timedelta, timezone

from rackhelm import analytics, demo, service, store
from rackhelm.schemas import Rack, ReadingIn


def make_reading(minute, temp):
    return ReadingIn(
        rack_id="Z01-R01", observed_at=datetime(2026, 5, 1, tzinfo=timezone.utc)
        + timedelta(minutes=minute), inlet_c=temp, outlet_c=temp+12,
        power_kw=12, gpu_util_pct=55, fan_rpm=6400,
        ecc_errors=0, packet_loss_pct=0.01,
    )


def test_facility_topology_and_fleet_inventory():
    racks, coolers, feeds = demo.facility_model()
    assert len(racks) == 48
    assert len(coolers) == 8
    assert len(feeds) == 8
    assert len({r.rack_id for r in racks}) == 48
    assert len({(r.zone,r.row,r.position) for r in racks}) == 48
    assert sum(r.rack_type == "GPU" for r in racks) == 28


def test_seeded_site_has_telemetry_and_alerts(site):
    result = service.dashboard_state()
    assert result["kpis"]["rack_count"] == 48
    assert len(result["zones"]) == 4
    assert result["kpis"]["it_load_kw"] > 0
    assert result["kpis"]["estimated_pue"] > 1
    assert any(r["severity"] in ("warning", "critical") for r in result["racks"])
    assert store.incidents(limit=100)


def test_seed_is_idempotent(site):
    before = store.audit_valid()["events_checked"]
    count = len(store.rack_history("Z02-R04", 500))
    store.initialize()
    assert store.audit_valid()["events_checked"] == before
    assert len(store.rack_history("Z02-R04", 500)) == count


def test_synthetic_sampler_reproducible_when_anchored():
    racks, _, _ = demo.facility_model()
    anchor = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert demo.synthetic_readings(racks,now=anchor) == demo.synthetic_readings(racks,now=anchor)


def test_regression_warming_rate():
    series = [make_reading(i * 5, 21 + i * .5) for i in range(12)]
    assert abs(analytics.trend_c_per_minute(series) - .1) < .0001


def test_regression_handles_flat_and_insufficient():
    assert analytics.trend_c_per_minute([make_reading(0,21)]) == 0
    assert analytics.trend_c_per_minute([make_reading(i * 5,21) for i in range(10)]) == 0


def test_robust_anomaly_uses_noise_floor():
    series = [make_reading(i*5,21 + (i%2)*.02) for i in range(14)]
    series[-1] = make_reading(65,30)
    assert analytics.robust_temperature_anomaly(series) > 10


def test_time_to_limit_and_explanations():
    rack = demo.facility_model()[0][0]
    series = [make_reading(i*5,22 + i*.45) for i in range(12)]
    result = analytics.diagnostics(rack,series,at=series[-1].observed_at)
    assert result["eta_to_limit_minutes"] is not None
    assert result["risk"] > 30
    assert any(s["code"] == "SUSTAINED_WARMING" for s in result["signals"])


def test_no_telemetry_is_unknown():
    rack = demo.facility_model()[0][0]
    assert analytics.diagnostics(rack,[])["severity"] == "unknown"
    assert analytics.diagnostics(rack,[])["signals"][0]["code"] == "NO_TELEMETRY"


def test_thermal_ceiling_configurable():
    rack = Rack(**{**demo.facility_model()[0][0].model_dump(), "temp_limit_c": 23})
    rows = [make_reading(i*5,24) for i in range(10)]
    result = analytics.diagnostics(rack,rows,at=rows[-1].observed_at)
    assert any(x["code"] == "INLET_CEILING_EXCEEDED" for x in result["signals"])
    assert result["eta_to_limit_minutes"] == 0


def test_simulation_monotonic_and_non_actuating(site):
    _, zones = service.rack_states()
    zone = zones[1]
    base = analytics.simulate_cooling_loss(zone)
    worst = analytics.simulate_cooling_loss(zone,cooling_drop_pct=90,gpu_load_delta_pct=50)
    assert worst["estimated_peak_inlet_c"] > base["estimated_peak_inlet_c"]
    assert worst["capacity_gap_kw"] >= base["capacity_gap_kw"]
    assert worst["control_actions_executed"] is False


def test_cooling_n1_reflects_largest_unit_loss():
    racks, cooling, feeds = demo.facility_model()
    group = [{**r.model_dump(), "power_kw":10, "inlet_c":22} for r in racks]
    zones = analytics.redundancy(group,cooling,feeds)
    z = next(z for z in zones if z["zone"] == "Z02")
    assert z["cooling_n1_headroom_kw"] == 137 - 120
    assert z["cooling_n1_pass"]


def test_cooling_failure_risk_detects_deficit():
    racks, cooling, feeds = demo.facility_model()
    group = [{**r.model_dump(), "power_kw":16, "inlet_c":22} for r in racks]
    zones = analytics.redundancy(group,cooling,feeds)
    assert all(not z["cooling_n1_pass"] for z in zones)
    assert zones[1]["cooling_n1_headroom_kw"] < 0


def test_risk_bounded_with_pathological_inputs():
    rack = demo.facility_model()[0][0]
    series = [make_reading(i*5,28+i*.7) for i in range(15)]
    curr=series[-1].model_copy(update={"power_kw":rack.max_kw,"ecc_errors":50,"packet_loss_pct":40,"fan_rpm":100})
    series[-1]=curr
    risk=analytics.diagnostics(rack,series,zone_n1_headroom_kw=-100,at=curr.observed_at)
    assert 0 <= risk["risk"] <= 100
    assert risk["severity"] == "critical"


def test_recommendations_advisory_only(site):
    report=service.dashboard_state()
    assert report["recommendations"]
    assert all(r["mode"] == "advisory_only" for r in report["recommendations"])