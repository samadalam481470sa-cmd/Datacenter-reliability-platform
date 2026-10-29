from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rackhelm.redfish import Config, Endpoint, convert, load_config


def endpoint(**kwargs):
    return Endpoint(rack_id="Z01-R01", base_url="https://bmc.internal.example",
                    username_env="RACKHELM_REDFISH_USER", password_env="RACKHELM_REDFISH_PASS",
                    max_power_kw=20, **kwargs)


def test_valid_redfish_conversion():
    thermal = {"Temperatures": [{"Name": "Inlet Temp", "ReadingCelsius": 24},
                                 {"Name": "Outlet Temp", "ReadingCelsius": 35}],
               "Fans": [{"Reading": 5500, "ReadingUnits": "RPM"}]}
    power = {"PowerControl": [{"PowerConsumedWatts": 6500}]}
    reading = convert(endpoint(), thermal, power, observed_at=datetime.now(timezone.utc))
    assert reading.inlet_c == 24
    assert reading.outlet_c == 35
    assert reading.power_kw == 6.5
    assert reading.fan_rpm == 5500
    assert reading.rack_id == "Z01-R01"


def test_reject_missing_critical_sensors():
    with pytest.raises(ValueError, match="inlet"):
        convert(endpoint(), {"Temperatures": [], "Fans": []}, {"PowerControl": []})
    with pytest.raises(ValueError, match="power"):
        convert(endpoint(), {"Temperatures": [{"Name": "Inlet", "ReadingCelsius": 22}],
                             "Fans": [{"Reading": 1000, "ReadingUnits": "RPM"}]}, {})


def test_reject_non_rpm_fans():
    with pytest.raises(ValueError, match="RPM"):
        convert(endpoint(), {"Temperatures": [{"Name": "Inlet", "ReadingCelsius": 22}],
                             "Fans": [{"Reading": 50, "ReadingUnits": "Percent"}]},
                {"PowerControl": [{"PowerConsumedWatts": 400}]})


@pytest.mark.parametrize("url", ["http://bmc.internal", "https://user:pass@bmc.internal",
                                   "https://bmc.internal/redfish/v1", "https://bmc.internal?x=1"])
def test_reject_insecure_redfish_origin(url):
    with pytest.raises(ValidationError):
        Endpoint(rack_id="Z01-R01", base_url=url,
                 username_env="RACKHELM_REDFISH_USER", password_env="RACKHELM_REDFISH_PASS",
                 max_power_kw=20)


def test_reject_resource_path_traversal():
    with pytest.raises(ValidationError):
        endpoint(thermal_path="/redfish/v1/../../etc/passwd")


def test_sink_enforces_https_for_remote():
    with pytest.raises(ValidationError):
        Config(endpoints=[endpoint()], rackhelm_url="http://example.com")


def test_config_example_parses():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "config" / "redfish.example.json"
    config = load_config(path)
    assert len(config.endpoints) == 1