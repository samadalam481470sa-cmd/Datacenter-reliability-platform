"""Runnable end-to-end smoke check against http://127.0.0.1:8000."""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

HOST = os.getenv("RACKHELM_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def get(path: str) -> dict | str:
    with urlopen(HOST + path, timeout=10) as response:
        body = response.read()
        return json.loads(body) if "json" in response.headers.get("Content-Type", "") else body.decode()


def main() -> None:
    assert get("/health")["status"] == "ok"
    data = get("/api/v1/overview")
    assert data["kpis"]["rack_count"] == 48
    assert any(r["signals"] for r in data["racks"])
    assert get("/api/v1/racks/Z02-R04/history")["readings"]
    assert get("/api/v1/incidents")["incidents"]
    scenario = get("/api/v1/scenario?zone=Z02&cooling_drop_pct=65")
    assert scenario["zone"] == "Z02"
    assert "Rack thermal map" in get("/")
    assert "renderHeatmap" in get("/assets/app.js")
    try:
        urlopen(Request(HOST + "/api/v1/audit/verify"), timeout=10)
    except HTTPError as error:
        assert error.code == 503, error.code  # no operator secret configured
    else:
        raise AssertionError("Unauthenticated audit verification unexpectedly permitted")
    print("PASS: health, overview, risk signals, rack history, incidents, what-if, UI and auth boundary")


if __name__ == "__main__":
    main()