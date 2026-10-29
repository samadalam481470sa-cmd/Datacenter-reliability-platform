"""Prometheus gauges with bounded physical-asset labels, served behind operator auth."""

from __future__ import annotations

from rackhelm import service


def metrics_text() -> str:
    overview = service.dashboard_state()
    k = overview["kpis"]
    lines = [
        "# HELP rackhelm_rack_inlet_c Current rack inlet temperature in Celsius",
        "# TYPE rackhelm_rack_inlet_c gauge",
    ]
    for rack in overview["racks"]:
        # Rack identifiers and zones are generated/validated, never arbitrary telemetry labels.
        labels = f'rack="{rack["rack_id"]}",zone="{rack["zone"]}"'
        if rack["inlet_c"] is not None:
            lines.append(f'rackhelm_rack_inlet_c{{{labels}}} {rack["inlet_c"]}')
    lines.extend(["# TYPE rackhelm_rack_power_kw gauge"])
    for rack in overview["racks"]:
        labels = f'rack="{rack["rack_id"]}",zone="{rack["zone"]}"'
        lines.append(f'rackhelm_rack_power_kw{{{labels}}} {rack["power_kw"]}')
    lines.extend(["# TYPE rackhelm_rack_risk_index gauge"])
    for rack in overview["racks"]:
        labels = f'rack="{rack["rack_id"]}",zone="{rack["zone"]}"'
        lines.append(f'rackhelm_rack_risk_index{{{labels}}} {rack["risk"]}')
    lines.extend(["# TYPE rackhelm_zone_cooling_n1_headroom_kw gauge"])
    for zone in overview["zones"]:
        lines.append(f'rackhelm_zone_cooling_n1_headroom_kw{{zone="{zone["zone"]}"}} '
                     f'{zone["cooling_n1_headroom_kw"]}')
    lines.extend([
        "# TYPE rackhelm_it_power_kw gauge",
        f'rackhelm_it_power_kw {k["it_load_kw"]}',
        "# TYPE rackhelm_estimated_pue gauge",
        f'rackhelm_estimated_pue {k["estimated_pue"]}',
        "# TYPE rackhelm_racks_at_risk gauge",
        f'rackhelm_racks_at_risk {k["affected_racks"]}',
        "# TYPE rackhelm_open_incidents gauge",
        f'rackhelm_open_incidents {k["open_incidents"]}',
    ])
    return "\n".join(lines) + "\n"