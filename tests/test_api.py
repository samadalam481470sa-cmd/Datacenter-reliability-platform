from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from rackhelm.api import app


@pytest.fixture
def client(site):
    return TestClient(app)


def test_home_and_headers(client):
    response=client.get("/")
    assert response.status_code==200
    assert "Rack thermal map" in response.text
    assert response.headers["x-frame-options"]=="DENY"
    assert response.headers["cache-control"]=="no-store"
    assert client.get("/assets/app.js").status_code==200
    assert client.get("/assets/styles.css").status_code==200


def test_live_summary(client):
    r=client.get("/api/v1/overview")
    assert r.status_code==200
    summary=r.json()
    assert summary["kpis"]["rack_count"]==48
    assert len(summary["racks"])==48
    assert len(summary["zones"])==4
    assert summary["advisory_only"]
    assert summary["kpis"]["estimated_pue"]>1


def test_racks_zone_filter_and_unknown(client):
    assert len(client.get("/api/v1/racks?zone=Z02").json()["racks"])==12
    assert client.get("/api/v1/racks?zone=Z99").status_code==422
    assert client.get("/api/v1/racks/Z99-R99/history").status_code==404
    assert client.get("/api/v1/racks/Z02-R04/diagnostics").status_code==200
    data=client.get("/api/v1/racks/Z02-R04/history").json()["readings"]
    assert len(data)==36


def test_scenario_increases_with_cooling_loss(client):
    zero=client.get("/api/v1/scenario?zone=Z02&cooling_drop_pct=0").json()
    drop=client.get("/api/v1/scenario?zone=Z02&cooling_drop_pct=90").json()
    assert drop["estimated_peak_inlet_c"]>zero["estimated_peak_inlet_c"]
    assert drop["control_actions_executed"] is False
    assert client.get("/api/v1/scenario?zone=Z02&cooling_drop_pct=110").status_code==422


def test_secure_mode_blocks_all_read_apis_and_public_home(client,monkeypatch):
    monkeypatch.setenv("RACKHELM_MODE","secure")
    assert client.get("/").status_code==404
    assert client.get("/api/v1/overview").status_code==503
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY","aSecureOperatorKey_2026_WithMixedCharacters")
    assert client.get("/api/v1/overview").status_code==401
    assert client.get("/api/v1/overview",headers={"X-API-Key":"aSecureOperatorKey_2026_WithMixedCharacters"}).status_code==200


def test_ingest_requires_credential(client,monkeypatch):
    assert client.post("/api/v1/telemetry/batch",json={"readings":[]}).status_code==503
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY","aSecureOperatorKey_2026_WithMixedCharacters")
    assert client.post("/api/v1/telemetry/batch",json={"readings":[]}).status_code==401
    sample = {"rack_id": "Z01-R01", "observed_at": datetime.now(timezone.utc).isoformat(),
              "inlet_c": 22, "outlet_c": 34, "power_kw": 9, "gpu_util_pct": 60,
              "fan_rpm": 6000, "ecc_errors": 0, "packet_loss_pct": 0.01}
    assert client.post("/api/v1/telemetry/batch",json={"readings":[sample]},headers={"X-API-Key":"aSecureOperatorKey_2026_WithMixedCharacters"}).status_code==403
    monkeypatch.setenv("RACKHELM_ALLOW_DEMO_INGEST", "1")
    assert client.post("/api/v1/telemetry/batch",json={"readings":[]},headers={"X-API-Key":"aSecureOperatorKey_2026_WithMixedCharacters"}).status_code==422


def test_ingestion_live_and_audit(client,monkeypatch):
    monkeypatch.setenv("RACKHELM_ALLOW_DEMO_INGEST", "1")
    key="aSecureOperatorKey_2026_WithMixedCharacters"
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY",key)
    headers={"X-API-Key":key}
    reading={"rack_id":"Z02-R04","observed_at":datetime.now(timezone.utc).replace(microsecond=314159).isoformat(),
             "inlet_c":29.4,"outlet_c":41,"power_kw":18,"gpu_util_pct":75,
             "fan_rpm":1200,"ecc_errors":3,"packet_loss_pct":0.1}
    response=client.post("/api/v1/telemetry/batch",headers=headers,json={"readings":[reading]})
    assert response.status_code==200,response.text
    assert response.json()["inserted"]==1
    assert client.post("/api/v1/telemetry/batch",headers=headers,json={"readings":[reading]}).json()["duplicate"]==1
    result=client.get("/api/v1/racks/Z02-R04/diagnostics").json()
    assert result["inlet_c"]==29.4
    assert result["risk"]>=70
    assert client.get("/api/v1/audit/verify",headers=headers).json()["valid"]


def test_operator_incident_resolution(client,monkeypatch):
    key="aSecureOperatorKey_2026_WithMixedCharacters"
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY",key)
    headers={"X-API-Key":key}
    i=client.get("/api/v1/incidents").json()["incidents"][0]
    response=client.post("/api/v1/incidents/"+i["incident_id"]+"/status",headers=headers,
       json={"status":"acknowledged","operator":"operator-1","note":"Inspected dashboard alarm"})
    assert response.status_code==200
    assert response.json()["status"]=="acknowledged"
    assert client.post("/api/v1/incidents/not-real/status",headers=headers,
       json={"status":"resolved","operator":"operator-1","note":"No matching incident"}).status_code==404


def test_no_anonymous_incident_update(client):
    incidents=client.get("/api/v1/incidents").json()["incidents"]
    assert incidents
    assert client.post("/api/v1/incidents/"+incidents[0]["incident_id"]+"/status",
      json={"status":"resolved","operator":"analyst","note":"All clear"}).status_code==503


def test_invalid_and_nonfinite_sensor_data_rejected(client,monkeypatch):
    monkeypatch.setenv("RACKHELM_ALLOW_DEMO_INGEST", "1")
    monkeypatch.setenv("RACKHELM_OPERATOR_KEY","aSecureOperatorKey_2026_WithMixedCharacters")
    invalid={"rack_id":"Z01-R01","observed_at":"2026-05-01T00:00:00", "inlet_c":"NaN",
       "outlet_c":20,"power_kw":3,"gpu_util_pct":2,"fan_rpm":200,"ecc_errors":0,"packet_loss_pct":0}
    assert client.post("/api/v1/telemetry/batch",headers={"X-API-Key":"aSecureOperatorKey_2026_WithMixedCharacters"},json={"readings":[invalid]}).status_code==422


def test_max_body_bytes(client):
    response=client.post("/api/v1/telemetry/batch",data="x"*1000001)
    assert response.status_code==413