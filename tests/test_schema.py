from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rackhelm.schemas import BatchIn, ReadingIn


def valid():
    return dict(rack_id="Z01-R01",observed_at=datetime.now(timezone.utc),
                inlet_c=21,outlet_c=32,power_kw=13,gpu_util_pct=75,
                fan_rpm=7000,ecc_errors=0,packet_loss_pct=.02)


def test_reject_naive_timestamps():
    with pytest.raises(ValidationError):
        ReadingIn(**{**valid(),"observed_at":datetime(2026,5,1)})


def test_reject_nonfinite_and_negative_sensor_values():
    for updates in [{"inlet_c":float('nan')},{"inlet_c":float('inf')},
                    {"power_kw":-1},{"gpu_util_pct":101},{"fan_rpm":-1}]:
        with pytest.raises(ValidationError):
            ReadingIn(**{**valid(),**updates})


def test_schema_forbids_unknown_extra_fields():
    with pytest.raises(ValidationError):
        ReadingIn(**{**valid(),"untrusted":"not allowed"})


def test_reject_batch_over_200():
    reading=ReadingIn(**valid())
    with pytest.raises(ValidationError):
        BatchIn(readings=[reading]*201)