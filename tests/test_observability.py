from fastapi.testclient import TestClient

from rackhelm.api import app
from rackhelm.observability import metrics_text


def test_prometheus_metrics_have_fixed_safe_asset_labels(site):
    text = metrics_text()
    assert 'rackhelm_rack_inlet_c{rack="Z02-R04",zone="Z02"}' in text
    assert text.count('rackhelm_rack_power_kw{rack=') == 48
    assert "rackhelm_zone_cooling_n1_headroom_kw{zone=" in text
    assert "rackhelm_estimated_pue" in text
    assert "192.0.2." not in text


def test_metrics_require_operator_even_in_demo(site,monkeypatch):
    client=TestClient(app)
    assert client.get("/metrics").status_code==503
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY","aSecureOperatorKey_2026_WithMixedCharacters")
    assert client.get("/metrics").status_code==401
    response=client.get("/metrics",headers={"X-API-Key":"aSecureOperatorKey_2026_WithMixedCharacters"})
    assert response.status_code==200
    assert "rackhelm_it_power_kw" in response.text