from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from idesktop_v2.api.app import app


def _wait_for_terminal(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/engineering/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] in {"completed", "failed", "cancelled"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("run did not finish before timeout")


def test_python_fem_run_produces_real_artifact_and_report(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.post(
        "/api/engineering/runs",
        json={
            "lane": "python-fem",
            "ownerId": "engineering-test",
            "task": {
                "task_id": "eng-1",
                "load_case": "cantilever",
                "geometry": {"nelx": 8, "nely": 4},
                "params": {"max_iter": 2, "volfrac": 0.4},
            },
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    payload = _wait_for_terminal(client, run_id)
    assert payload["status"] == "completed"
    assert payload["lane"] == "python-fem"
    assert payload["provenance"]["resultKind"] == "solver"
    assert payload["files"]
    assert payload["metrics"]["iterations"] >= 1

    artifacts = client.get(f"/api/engineering/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    assert artifacts.json()["files"]

    report = client.post(f"/api/engineering/runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["relativePath"].endswith(".md")


def test_run_can_be_cancelled_without_being_reported_as_completed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.post(
        "/api/engineering/runs",
        json={
            "lane": "python-fem",
            "ownerId": "engineering-cancel",
            "task": {
                "load_case": "cantilever",
                "geometry": {"nelx": 30, "nely": 15},
                "params": {"max_iter": 80},
            },
        },
    )
    assert response.status_code == 202
    run_id = response.json()["runId"]
    cancel = client.post(f"/api/engineering/runs/{run_id}/cancel")
    assert cancel.status_code == 202
    payload = _wait_for_terminal(client, run_id)
    assert payload["status"] == "cancelled"
    assert payload.get("error") is None


def test_run_stream_replays_progress_events(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.post(
        "/api/engineering/runs",
        json={
            "lane": "python-fem",
            "ownerId": "engineering-stream",
            "task": {"load_case": "cantilever", "geometry": {"nelx": 6, "nely": 3}, "params": {"max_iter": 2}},
        },
    )
    run_id = response.json()["runId"]
    payload = _wait_for_terminal(client, run_id)
    assert payload["status"] == "completed"
    # The non-WebSocket event endpoint is intentionally a deterministic replay helper for CLI clients.
    events = client.get(f"/api/engineering/runs/{run_id}/events")
    assert events.status_code == 200
    assert any(item["type"] == "progress" for item in events.json()["events"])


def test_local_matlab_lane_fails_with_infrastructure_evidence_when_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IDESKTOP_MATLAB_PATH", str(tmp_path / "missing-matlab"))
    client = TestClient(app)
    response = client.post("/api/engineering/runs", json={"lane": "local-matlab", "ownerId": "engineering-matlab", "task": {"load_case": "cantilever"}})
    assert response.status_code == 202
    payload = _wait_for_terminal(client, response.json()["runId"])
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "MATLAB_INFRASTRUCTURE"
    assert payload["error"]["source"] == "matlab"


def test_compiled_runtime_lane_does_not_fallback_to_python(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("IDESKTOP_RUNTIME_SOLVER", raising=False)
    client = TestClient(app)
    response = client.post("/api/engineering/runs", json={"lane": "compiled-runtime", "ownerId": "engineering-runtime", "task": {"load_case": "cantilever"}})
    assert response.status_code == 422
    assert "runtimeProfileId" in response.text

def test_engineering_artifact_download_is_allowlisted(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    created = client.post("/api/engineering/runs", json={"lane": "python-fem", "ownerId": "download-test", "task": {"load_case": "cantilever", "geometry": {"nelx": 6, "nely": 3}, "params": {"max_iter": 1}}}).json()
    payload = _wait_for_terminal(client, created["runId"])
    relative = payload["files"][0]["relativePath"]
    assert client.get(f"/api/engineering/runs/{created['runId']}/files/{relative}").status_code == 200
    assert client.get(f"/api/engineering/runs/{created['runId']}/files/../result.json").status_code in {400, 404}

def test_engineering_run_rejects_invalid_complete_parameter_configuration() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/engineering/runs",
        json={
            "lane": "python-fem",
            "ownerId": "engineering-test",
            "task": {
                "task_id": "invalid-config",
                "load_case": "unsupported",
                "geometry": {"nelx": 0, "nely": 8, "nelz": 6},
                "params": {"volfrac": 1.2, "penal": 0, "rmin": 0, "max_iter": 5, "min_iter": 10, "filter_strategy": "unknown", "accuracy": "ultra"},
            },
        },
    )
    assert response.status_code == 422