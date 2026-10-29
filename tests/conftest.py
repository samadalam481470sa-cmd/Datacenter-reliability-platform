from __future__ import annotations

import pytest

from rackhelm import store


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("RACKHELM_MODE", "demo")
    monkeypatch.setenv("RACKHELM_DB_PATH", str(tmp_path / "site.db"))
    monkeypatch.delenv("RACKHELM_OPERATOR_KEY", raising=False)
    monkeypatch.delenv("RACKHELM_ALLOW_DEMO_INGEST", raising=False)
    store.initialize()
    yield