"""Validated, explicitly bounded data-plane inputs.

Rack inlet temperatures and capacities are configuration-specific; 27 C is a
*demonstration-only* advisory ceiling, never a universally safe setpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Rack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rack_id: str = Field(pattern=r"^[A-Z][0-9]{2}-R[0-9]{2}$")
    zone: str = Field(pattern=r"^[A-Z][0-9]{2}$")
    row: int = Field(ge=1, le=30)
    position: int = Field(ge=1, le=30)
    rack_type: Literal["GPU", "CPU", "STORAGE", "NETWORK"]
    max_kw: float = Field(gt=0, le=100)
    cooling_group: str = Field(min_length=1, max_length=30)
    power_group: str = Field(min_length=1, max_length=30)
    temp_limit_c: float = Field(ge=16, le=40)
    asset_count: int = Field(ge=1, le=128)


class CoolingUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    unit_id: str = Field(min_length=1, max_length=40)
    zone: str = Field(pattern=r"^[A-Z][0-9]{2}$")
    capacity_kw: float = Field(gt=0, le=400)
    state: Literal["online", "degraded", "offline"] = "online"
    availability: float = Field(ge=0, le=1, default=1)


class PowerFeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feed_id: str = Field(min_length=1, max_length=40)
    zone: str = Field(pattern=r"^[A-Z][0-9]{2}$")
    capacity_kw: float = Field(gt=0, le=1000)
    state: Literal["online", "degraded", "offline"] = "online"


class ReadingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rack_id: str = Field(pattern=r"^[A-Z][0-9]{2}-R[0-9]{2}$")
    observed_at: datetime
    inlet_c: float = Field(ge=-10, le=70, allow_inf_nan=False)
    outlet_c: float = Field(ge=-10, le=90, allow_inf_nan=False)
    power_kw: float = Field(ge=0, le=100, allow_inf_nan=False)
    gpu_util_pct: float = Field(ge=0, le=100, allow_inf_nan=False)
    fan_rpm: int = Field(ge=0, le=50000)
    ecc_errors: int = Field(ge=0, le=1_000_000)
    packet_loss_pct: float = Field(ge=0, le=100, allow_inf_nan=False)

    @field_validator("observed_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Sensor timestamps must include a UTC offset")
        from datetime import timezone

        return value.astimezone(timezone.utc)


class BatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    readings: list[ReadingIn] = Field(min_length=1, max_length=200)


class IncidentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["acknowledged", "resolved"]
    note: str = Field(min_length=3, max_length=500)
    operator: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9._ -]+$")