from __future__ import annotations

import struct

import numpy as np
from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop import research_router
from topoptpilot.service import ResearchService


def _research(service: ResearchService, *, goal: str = "验证真实科研工作流") -> dict:
    return service.create_research({
        "name": "TopOptPilot 2.0.2 定向测试",
        "goal": goal,
        "hypothesis": None,
        "budget_total": 8,
        "mode": "COPILOT",
    })


def test_missing_state_retry_is_read_only_and_requires_complete_action(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated, goal="")
        context = isolated.tools.research_get_context(created["id"])
        before = isolated.store.list_events(created["id"])
        config = research_router._research_config_template(created["id"])[0].model_dump()
        action = {
            "type": "apply_research_state",
            "goal": "在约束下最小化柔度",
            "hypothesis": "增大惩罚因子将降低灰度率",
            "optimizationConfig": config,
            "changedFields": ["goal", "hypothesis", "optimizationConfig"],
            "rationale": "补齐缺失研究状态",
        }
        monkeypatch.setattr(research_router, "_model_chat", lambda _messages: {
            "success": True,
            "content": "<topoptpilot-research-action>" + __import__("json").dumps(action, ensure_ascii=False) + "</topoptpilot-research-action>",
        })
        extracted = research_router._retry_missing_state_action(created["id"], context, "普通建议", [])
        assert extracted == [action]
        assert isolated.store.list_events(created["id"]) == before
        assert "optimization_config" not in (isolated.get_research(created["id"]).get("defaults") or {})
    finally:
        isolated.close()


def test_verified_engineering_scheme_imports_baseline_without_starting(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    created = _research(isolated)
    scheme = {
        "id": "scheme-v202", "name": "竖向工程基线", "runId": "run-v202",
        "configDigest": "a" * 64, "integrity": "verified",
        "config": {
            "dimension": "3D", "load_case": "vertical",
            "geometry": {"nelx": 24, "nely": 8, "nelz": 6},
            "params": {"volfrac": .4, "penal": 3, "rmin": 1.5, "min_iter": 4, "max_iter": 20},
            "material": {"preset": "normalized", "name": "参考材料", "E_GPa": 1, "nu": .3},
        },
        "run": {
            "status": "completed", "configDigest": "a" * 64,
            "files": [{"relativePath": "result_summary.json"}],
            "metrics": {"compliance": 12.5, "volumeFraction": .4, "grayRatio": .02},
            "provenance": {"resultKind": "solver", "backend": "local-matlab"},
        },
    }
    monkeypatch.setattr(research_router.comparison_schemes, "get", lambda _scheme_id: scheme)
    try:
        response = TestClient(app).post(
            f"/api/research/{created['id']}/engineering-baselines",
            json={"schemeId": scheme["id"]},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["optimizationConfig"]["bcType"] == "MBB"
        assert payload["baseline"]["runId"] == "run-v202"
        assert payload["research"]["experiments"] == []
        assert isolated.store.list_events(created["id"])[-1]["kind"] == "ENGINEERING_BASELINE_IMPORTED"
    finally:
        isolated.close()


def test_research_visualization_uses_fortran_float32_and_rejects_invalid_stress(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    created = _research(isolated)
    experiment_id = "E01"
    isolated.store.create_experiment({
        "id": experiment_id, "research_id": created["id"], "purpose": "真实可视化",
        "fidelity": "F2 — MATLAB 3D Coarse", "mesh_level": "coarse", "backend": "matlab",
        "parameters": {"nelx": 2, "nely": 2, "nelz": 2}, "status": "SUCCESS", "round_number": 1,
    })
    result = {
        "objective": {"compliance": 10.0}, "constraints": {"volume_fraction": .4},
        "quality": {"gray_ratio": .125, "connected_components": 1},
        "artifacts": {"history": [{"iteration": 1, "compliance": 10.0}], "lineage_ids": ["AR-REAL"]},
    }
    isolated.store.update_experiment(experiment_id, status="SUCCESS", result=result)
    artifact_dir = tmp_path / created["id"] / "artifacts" / experiment_id
    artifact_dir.mkdir(parents=True)
    density = np.arange(8, dtype=np.float64).reshape((2, 2, 2), order="F") / 10
    np.save(artifact_dir / "density.npy", density)
    np.save(artifact_dir / "stress.npy", np.ones((2, 2), dtype=float))
    client = TestClient(app)
    try:
        manifest = client.get(f"/api/research/{created['id']}/experiments/{experiment_id}/visualization")
        assert manifest.status_code == 200
        assert manifest.json()["shape"] == [2, 2, 2]
        assert manifest.json()["order"] == "F"
        assert manifest.json()["hasStress"] is False
        raw = client.get(f"/api/research/{created['id']}/experiments/{experiment_id}/visualization/density")
        assert raw.status_code == 200
        assert struct.unpack("<8f", raw.content) == tuple(np.asarray(density, dtype="<f4").ravel(order="F"))
        assert client.get(f"/api/research/{created['id']}/experiments/{experiment_id}/visualization/stress").status_code == 404

        stress = density * 100
        np.save(artifact_dir / "stress.npy", stress)
        assert client.get(f"/api/research/{created['id']}/experiments/{experiment_id}/visualization").json()["hasStress"] is True
        stress_raw = client.get(f"/api/research/{created['id']}/experiments/{experiment_id}/visualization/stress")
        assert struct.unpack("<8f", stress_raw.content) == tuple(np.asarray(stress, dtype="<f4").ravel(order="F"))
    finally:
        isolated.close()


def test_workflow_progress_counts_only_current_round_real_terminal_experiments() -> None:
    research = {
        "events": [
            {"title": "ROUND_STARTED", "payload": {}},
            {"title": "WORKFLOW_CONTEXT_COMPLETED", "payload": {}},
            {"title": "THREE_PLAN_SUBMITTED", "payload": {}},
        ],
        "experiments": [
            {"id": "OLD", "round_number": 1, "status": "SUCCESS"},
            {"id": "E02", "round_number": 2, "status": "SUCCESS"},
            {"id": "E03", "round_number": 2, "status": "RUNNING"},
            {"id": "E04", "round_number": 2, "status": "FAILED"},
        ],
        "decisions": [], "current_round": 1, "budget_used": 4, "budget_total": 8,
        "defaults": {}, "status": "RUNNING",
    }
    workflow = ResearchService._workflow_progress(research)
    assert workflow["round"] == 2
    assert workflow["stage"] == "experiments"
    experiment_step = next(item for item in workflow["steps"] if item["id"] == "experiments")
    assert experiment_step["experimentIds"] == ["E02", "E03", "E04"]
    assert experiment_step["result"] == "已完成 2 / 3 个真实方案"


def test_workflow_progress_reports_no_successful_route_without_inventing_a_best() -> None:
    research = {
        "events": [
            {"title": "ROUND_STARTED", "payload": {}},
            {"title": "EXPERIMENT_BATCH_COMPLETED", "payload": {}},
            {
                "title": "WORKFLOW_REFLECTION",
                "payload": {
                    "workflow_step": "selection",
                    "reflection": "无成功结果时不指定最优方案。",
                },
            },
        ],
        "experiments": [
            {"id": "E01", "round_number": 1, "status": "FAILED"},
            {"id": "E02", "round_number": 1, "status": "CANCELLED"},
            {"id": "E03", "round_number": 1, "status": "FAILED"},
        ],
        "decisions": [], "current_round": 0, "budget_used": 3, "budget_total": 8,
        "defaults": {}, "status": "RUNNING",
    }
    workflow = ResearchService._workflow_progress(research)
    selection = next(item for item in workflow["steps"] if item["id"] == "selection")
    assert selection["result"] == "本轮没有真实成功方案"
    assert selection["reflection"] == "无成功结果时不指定最优方案。"
    assert selection["evidenceIds"] == ["E01", "E02", "E03"]


def test_autonomous_no_approval_candidate_records_policy_reflection(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        created = isolated.create_research({
            "name": "自动审批反思测试", "goal": "验证审批边界", "hypothesis": "F0 可自动执行",
            "budget_total": 8, "mode": "AUTONOMOUS",
        })
        isolated.store.update_research(created["id"], mode="AUTONOMOUS", status="RUNNING")
        monkeypatch.setattr(isolated, "run_experiment", lambda _experiment_id: None)
        experiment = isolated.create_experiment(created["id"], {
            "purpose": "自动 Policy 边界测试",
            "fidelity": "F0 — MATLAB 2D Coarse",
            "mesh_level": "coarse",
            "backend": "python",
            "parameters": {"nelx": 8, "nely": 4, "volfrac": 0.4, "penal": 3.0, "rmin": 1.5},
            "requires_approval": False,
        })
        events = isolated.store.list_events(created["id"])
        approval_events = [
            event for event in events
            if (event.get("payload") or {}).get("workflow_step") == "approval"
            and experiment["id"] in (event.get("payload") or {}).get("experiment_ids", [])
        ]
        assert approval_events
        assert "Policy、Safety 与预算校验" in approval_events[-1]["payload"]["reflection"]
    finally:
        isolated.close()
