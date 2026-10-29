"""Deterministic, synthetic facility simulator. Never contacts real control systems."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from rackhelm.schemas import CoolingUnit, PowerFeed, Rack, ReadingIn

ZONES = ("Z01", "Z02", "Z03", "Z04")


def facility_model() -> tuple[list[Rack], list[CoolingUnit], list[PowerFeed]]:
    racks = []
    cooling = []
    power = []
    for z, zone in enumerate(ZONES):
        for n in range(1, 13):
            kind = "GPU" if n <= 7 else "CPU" if n <= 10 else "STORAGE" if n == 11 else "NETWORK"
            cap = {"GPU": 25.0, "CPU": 17.0, "STORAGE": 12.0, "NETWORK": 8.0}[kind]
            racks.append(
                Rack(
                    rack_id=f"{zone}-R{n:02}", zone=zone, row=1 + (n - 1) // 6,
                    position=1 + (n - 1) % 6, rack_type=kind,
                    max_kw=cap, cooling_group=f"CRAC-{zone}",
                    power_group=f"PDU-{zone}", temp_limit_c=27.0,
                    asset_count=8 if kind == "GPU" else 14 if kind == "CPU" else 20,
                )
            )
        capacity = (155, 137, 155, 149)[z]
        cooling.extend(
            [CoolingUnit(unit_id=f"{zone}-CU-A", zone=zone, capacity_kw=capacity),
             CoolingUnit(unit_id=f"{zone}-CU-B", zone=zone, capacity_kw=capacity)]
        )
        power.extend(
            [PowerFeed(feed_id=f"{zone}-FEED-A", zone=zone, capacity_kw=190),
             PowerFeed(feed_id=f"{zone}-FEED-B", zone=zone, capacity_kw=190)]
        )
    return racks, cooling, power


def synthetic_readings(racks: list[Rack], *, now: datetime | None = None,
                       points: int = 36) -> list[ReadingIn]:
    rng = random.Random(48712)
    anchor = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    anchor = anchor.replace(second=0, microsecond=0)
    readings = []
    for step in range(points):
        minutes = (points - 1 - step) * 5
        timestamp = anchor - timedelta(minutes=minutes)
        for rack in racks:
            index = int(rack.rack_id.split("R")[-1])
            zone_num = int(rack.zone[-1])
            if rack.rack_type == "GPU":
                load_frac = 0.56 + 0.18 * math.sin(step / 8 + index * .33 + zone_num)
            else:
                load_frac = 0.44 + 0.16 * math.sin(step / 7 + index * .4)
            load_frac = max(0.25, min(0.91, load_frac))
            power_kw = rack.max_kw * load_frac
            inlet = 20.6 + zone_num * 0.32 + power_kw * 0.13 + 0.22 * math.sin(step / 4 + index)
            inlet += rng.uniform(-.21, .21)
            fan = 6800 if rack.rack_type == "GPU" else 5100
            ecc = 0
            packet_loss = 0.02
            # Bad rack develops blocked airflow/fan degradation over the last 120 minutes.
            if rack.rack_id == "Z02-R04" and step >= 10:
                progress = (step - 10) / max(1, points - 11)
                inlet += progress * 6.0
                fan = int(6200 - progress * 3900)
                ecc = 2 if progress > .65 else 0
            # High-density GPU rack gets close to the electrical headroom.
            if rack.rack_id == "Z03-R08" and step >= 18:
                power_kw = rack.max_kw * (0.79 + (step - 18) / max(1, points - 19) * .22)
                inlet += 1.5
            # Network quality incident correlated with a specific rack.
            if rack.rack_id == "Z04-R12" and step >= 26:
                packet_loss = 0.6 + (step - 26) * .14
            # Localized temperature spike elsewhere.
            if rack.rack_id == "Z01-R07" and step >= 30:
                inlet += (step - 29) * .62
            reading = ReadingIn(
                rack_id=rack.rack_id, observed_at=timestamp,
                inlet_c=round(inlet, 3), outlet_c=round(inlet + 7.0 + load_frac * 5.0, 3),
                power_kw=round(power_kw, 3), gpu_util_pct=round(load_frac * 100, 2),
                fan_rpm=fan, ecc_errors=ecc, packet_loss_pct=round(packet_loss, 3),
            )
            readings.append(reading)
    return readings