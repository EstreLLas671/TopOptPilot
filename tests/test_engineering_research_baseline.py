from __future__ import annotations

import warnings
from fastapi.testclient import TestClient
from pydantic.warnings import UnsupportedFieldAttributeWarning

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.engineering.runs import manager


def test_research_baseline_requires_a_completed_real_engineering_run() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", UnsupportedFieldAttributeWarning)
        response = TestClient(app).post("/api/research/from-engineering-run/missing", json={"name": "baseline", "budgetTotal": 8})
    assert response.status_code == 404


def test_research_baseline_does_not_submit_an_experiment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    created = client.post("/api/engineering/runs", json={"lane": "python-fem", "ownerId": "baseline", "task": {"load_case": "cantilever", "geometry": {"nelx": 6, "nely": 3}, "params": {"max_iter": 1}}}).json()
    import time
    for _ in range(100):
        record = manager.get(created["runId"])
        if record and record.status.value in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)
    response = client.post(f"/api/research/from-engineering-run/{created['runId']}", json={"name": "工程基线研究", "budgetTotal": 8})
    assert response.status_code == 201
    research = response.json()
    assert research["constraints"]["engineering_baseline"]["runId"] == created["runId"]
    assert research["budget_total"] == 8
    assert research["experiments"] == []
