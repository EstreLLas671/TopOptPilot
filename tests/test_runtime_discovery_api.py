from __future__ import annotations

from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.engineering.runtime_discovery import RuntimeInstallation


def test_engineering_health_initializes_runtime_inventory(monkeypatch) -> None:
    from topoptpilot_desktop.engineering import router as engineering_router

    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(engineering_router.runtime_inventory, "snapshot", snapshot)

    response = TestClient(app).get("/api/engineering/health")

    assert response.status_code == 200
    assert calls == 1


def test_engineering_runtime_installations_returns_discovery_inventory(monkeypatch, tmp_path) -> None:
    from topoptpilot_desktop.engineering import router as engineering_router

    runtime_root = tmp_path / "MATLAB Runtime" / "R2025b"
    installation = RuntimeInstallation(
        release="R2025b",
        version="25.2.0",
        path=runtime_root,
        source="registry",
        usable=True,
        reason="MATLAB Runtime 安装完整",
        dll_path=runtime_root / "runtime" / "win64" / "mclmcrrt25_2.dll",
        uninstaller_path=runtime_root / "bin" / "win64" / "Uninstall_MATLAB_Runtime.exe",
    )
    monkeypatch.setattr(engineering_router.runtime_inventory, "refresh", lambda: [installation])

    response = TestClient(app).get("/api/engineering/runtime/installations")

    assert response.status_code == 200
    payload = response.json()
    assert payload["usable"] is True
    assert payload["installations"][0]["release"] == "R2025b"
    assert payload["installations"][0]["source"] == "registry"
    assert payload["installations"][0]["usable"] is True
