"""Read-only Redfish telemetry collector with explicit endpoint configuration.

Never performs Redfish writes, discovery scans, or TLS verification bypass.
Only inventory-listed resources are requested; the collector cannot control equipment.
"""
from __future__ import annotations

import base64
import json
import math
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rackhelm.schemas import ReadingIn


class Endpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rack_id: str = Field(pattern=r"^[A-Z][0-9]{2}-R[0-9]{2}$")
    base_url: str
    thermal_path: str = "/redfish/v1/Chassis/1/Thermal"
    power_path: str = "/redfish/v1/Chassis/1/Power"
    system_path: str | None = None
    username_env: str
    password_env: str
    ca_bundle: str | None = None
    max_power_kw: float = Field(gt=0, le=100)

    @field_validator("base_url")
    @classmethod
    def https_only(cls, value: str) -> str:
        u = urlsplit(value)
        if (u.scheme != "https" or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in ("", "/")):
            raise ValueError("Redfish endpoints must be HTTPS origins without embedded credentials")
        return value.rstrip("/")

    @field_validator("thermal_path", "power_path", "system_path")
    @classmethod
    def bounded_resource(cls, value: str | None) -> str | None:
        if value is not None and (not value.startswith("/redfish/v1/")
                                  or ".." in value or "?" in value or "#" in value
                                  or "//" in value or len(value) > 200):
            raise ValueError("Redfish resources must be explicit /redfish/v1/ paths")
        return value

    @field_validator("username_env", "password_env")
    @classmethod
    def env_var(cls, value: str) -> str:
        if not value.startswith("RACKHELM_REDFISH_") or not value.replace("_", "").isalnum():
            raise ValueError("Credential env vars must use RACKHELM_REDFISH_ prefix")
        return value


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoints: list[Endpoint] = Field(min_length=1, max_length=100)
    rackhelm_url: str = "http://127.0.0.1:8000"

    @field_validator("rackhelm_url")
    @classmethod
    def safe_sink(cls, value: str) -> str:
        u = urlsplit(value)
        if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
                or u.query or u.fragment or u.path not in ("", "/")
                or (u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"))):
            raise ValueError("RackHelm destination must use HTTPS or loopback HTTP")
        return value.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are forbidden for management endpoints")


def _request_json(url: str, *, username: str, password: str, ca_bundle: str | None,
                  origin: str) -> dict[str, Any]:
    if not url.startswith(origin + "/redfish/v1/"):
        raise ValueError("Redfish URL outside explicitly configured origin")
    context = ssl.create_default_context(cafile=ca_bundle)
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = Request(url, headers={"Accept": "application/json", "Authorization": "Basic " + auth}, method="GET")
    opener = build_opener(HTTPSHandler(context=context), NoRedirect())
    with opener.open(req, timeout=8) as response:
        if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) > 1_000_000:
            raise ValueError("Redfish payload exceeds 1 MB")
        data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Redfish payload exceeds 1 MB")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
        return result


def _metric(items: Any, name: str, *, aggregate: str = "mean") -> float | None:
    if not isinstance(items, list):
        return None
    values = []
    for item in items:
        if isinstance(item, dict):
            value = item.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                values.append(float(value))
    if not values:
        return None
    return sum(values) if aggregate == "sum" else sum(values) / len(values)


def _value(value: Any, default: float, lo: float, hi: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return max(lo, min(hi, float(value)))
    return default


def convert(endpoint: Endpoint, thermal: dict, power: dict, system: dict | None = None,
            *, observed_at: datetime | None = None) -> ReadingIn:
    """Normalize Redfish chassis sensors into RackHelm's rack-level schema.

    A rack must be represented by an explicitly chosen chassis. The reading is
    not an aggregate of all equipment in a rack unless the source is rack-level.
    Missing values remain conservative placeholders and are documented.
    """
    system = system or {}
    temps = thermal.get("Temperatures", [])
    inlet = [x for x in temps if isinstance(x, dict) and any(
        word in str(x.get("Name", "")).lower() for word in ("inlet", "intake", "ambient"))]
    outlet = [x for x in temps if isinstance(x, dict) and any(
        word in str(x.get("Name", "")).lower() for word in ("exhaust", "outlet"))]
    inlet_c = _metric(inlet, "ReadingCelsius")
    outlet_c = _metric(outlet, "ReadingCelsius")
    if inlet_c is None:
        raise ValueError("No inlet temperature sensor: refusing to invent a measurement")
    if outlet_c is None:
        outlet_c = inlet_c
    power_w = _metric(power.get("PowerControl", []), "PowerConsumedWatts", aggregate="sum")
    if power_w is None:
        raise ValueError("No power consumption sensor: refusing to invent a measurement")
    fans = _metric(thermal.get("Fans", []), "Reading")
    if fans is None:
        raise ValueError("No fan reading: refusing to invent a measurement")
    # Redfish fans may report percentage rather than RPM. Do not silently map percent to RPM.
    if any(x.get("ReadingUnits") != "RPM" for x in thermal.get("Fans", []) if isinstance(x, dict) and isinstance(x.get("Reading"), (int, float))):
        raise ValueError("Fan reading is not in RPM")
    gpu = system.get("Oem", {}).get("RackHelm", {}).get("GpuUtilizationPercent")
    ecc = system.get("Oem", {}).get("RackHelm", {}).get("EccErrors")
    packet = system.get("Oem", {}).get("RackHelm", {}).get("PacketLossPercent")
    # Optional vendor metrics are zero if not present; do not treat those as measured.
    return ReadingIn(
        rack_id=endpoint.rack_id, observed_at=observed_at or datetime.now(timezone.utc),
        inlet_c=_value(inlet_c, 0, -10, 70), outlet_c=_value(outlet_c, 0, -10, 90),
        power_kw=_value(power_w / 1000, 0, 0, 100),
        fan_rpm=int(_value(fans, 0, 0, 50000)),
        gpu_util_pct=_value(gpu, 0, 0, 100),
        ecc_errors=int(_value(ecc, 0, 0, 1_000_000)),
        packet_loss_pct=_value(packet, 0, 0, 100),
    )


def collect(endpoint: Endpoint) -> ReadingIn:
    username = os.getenv(endpoint.username_env)
    password = os.getenv(endpoint.password_env)
    if not username or not password:
        raise ValueError("Redfish credentials missing from configured environment variables")
    origin = endpoint.base_url
    thermal = _request_json(origin + endpoint.thermal_path, username=username, password=password,
                            ca_bundle=endpoint.ca_bundle, origin=origin)
    power = _request_json(origin + endpoint.power_path, username=username, password=password,
                          ca_bundle=endpoint.ca_bundle, origin=origin)
    system = (_request_json(origin + endpoint.system_path, username=username, password=password,
                            ca_bundle=endpoint.ca_bundle, origin=origin)
              if endpoint.system_path else None)
    return convert(endpoint, thermal, power, system)


def load_config(path: Path) -> Config:
    if not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("Config must be an existing file under 100 KB")
    config = Config.model_validate_json(path.read_text(encoding="utf-8"))
    origins = [e.base_url for e in config.endpoints]
    racks = [e.rack_id for e in config.endpoints]
    if len(origins) != len(set(origins)) or len(racks) != len(set(racks)):
        raise ValueError("Duplicate Redfish origin or rack ID")
    return config