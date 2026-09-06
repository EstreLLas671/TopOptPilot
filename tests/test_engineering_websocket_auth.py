from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.engineering.runs import RunCreateRequest, manager


def test_engineering_stream_requires_the_desktop_token(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TOPPILOT_DESKTOP_TOKEN", "desktop-secret")
    record = manager.submit(
        RunCreateRequest.model_validate(
            {
                "lane": "python-fem",
                "ownerId": "authenticated-stream",
                "task": {
                    "load_case": "cantilever",
                    "geometry": {"nelx": 6, "nely": 3},
                    "params": {"max_iter": 1},
                },
            }
        )
    )
    deadline = time.time() + 20
    while time.time() < deadline and manager.get(record.run_id).status.value not in {
        "completed",
        "failed",
        "cancelled",
    }:
        time.sleep(0.05)

    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(f"/api/engineering/runs/{record.run_id}/stream"):
            pass
    assert denied.value.code == 4401

    with client.websocket_connect(
        f"/api/engineering/runs/{record.run_id}/stream?token=desktop-secret"
    ) as websocket:
        assert websocket.receive_json()["type"] in {"queued", "status", "progress", "completed"}
