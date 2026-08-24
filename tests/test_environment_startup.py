from __future__ import annotations

from fastapi.testclient import TestClient

def test_sidecar_lifespan_initializes_engineering_environment(monkeypatch) -> None:
    import idesktop_v2.api.app as app_module

    calls = 0

    def initialize() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"matlab": [], "runtime": []}

    monkeypatch.setattr(app_module, "initialize_engineering_discovery", initialize)

    with TestClient(app_module.app) as client:
        assert client.get("/api/engineering/health").status_code == 200

    assert calls == 1

def test_matlab_inventory_is_initialized_once_then_explicitly_refreshed() -> None:
    from idesktop_v2.engineering.environment_discovery import MatlabInventory

    calls = 0

    def discover():
        nonlocal calls
        calls += 1
        return []

    inventory = MatlabInventory(discover=discover)

    assert inventory.initialized is False
    assert inventory.snapshot() == []
    assert inventory.snapshot() == []
    assert inventory.refresh() == []
    assert inventory.initialized is True
    assert calls == 2
