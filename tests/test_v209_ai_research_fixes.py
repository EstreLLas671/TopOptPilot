from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mcp.matlab_mcp.matlab_mcp_server import MatlabMcpWorker
from solver.topopt3d import _boundary_conditions_3d
from topoptpilot.api import fastapi_app
from topoptpilot.api.fastapi_app import FidelityStageDecisionRequest
from topoptpilot.executor.executor import build_solver_task
from topoptpilot.memory.research_memory import ResearchMemory
from topoptpilot.orchestrator.research_orchestrator import ResearchOrchestrator
from topoptpilot.schemas import ResearchCreate
from topoptpilot.service import ResearchService
from topoptpilot_desktop import research_router


def _optimization_config() -> dict:
    return {
        "version": 1,
        "dimension": "3d",
        "bcType": "L-bracket",
        "accuracy": "high",
        "dimensions": [6.0, 2.0, 1.5],
        "unit": "m",
        "cellSizeMeters": 0.25,
        "nelx": 24,
        "nely": 8,
        "nelz": 6,
        "volfrac": 0.4,
        "penal": 3.2,
        "rmin": 2.0,
        "maxIterations": 120,
        "minIterations": 30,
        "filterStrategy": "adaptive",
        "material": {
            "preset": "aluminum-6061-t6",
            "name": "Al 6061",
            "youngsModulusGPa": 68.9,
            "poissonRatio": 0.33,
            "densityKgM3": 2700.0,
            "yieldStrengthMPa": 276.0,
        },
    }


def _research_state() -> dict:
    config = _optimization_config()
    return {
        "id": "R-001",
        "name": "Neutral research",
        "goal": "Minimize compliance",
        "hypothesis": "A controlled change can improve compliance",
        "mode": "AUTONOMOUS",
        "geometry": {
            "dimension": "3d",
            "dimensions": config["dimensions"],
            "unit": config["unit"],
            "cell_size_m": config["cellSizeMeters"],
            "nelx": config["nelx"],
            "nely": config["nely"],
            "nelz": config["nelz"],
            "accuracy": config["accuracy"],
        },
        "material": {
            "preset": "aluminum-6061-t6",
            "name": "Al 6061",
            "E_GPa": 68.9,
            "nu": 0.33,
            "density_kg_m3": 2700.0,
            "yield_strength_MPa": 276.0,
        },
        "loads": [{"type": "vertical", "magnitude": 2.0}],
        "boundary_conditions": {"type": "L-bracket"},
        "constraints": {"volume_fraction": 0.4, "gray_max": 0.05, "connected": True},
        "locks": {},
        "budgets": {"total": 20, "f0": 6, "f1": 6, "f2": 4, "f3": 4},
        "budget_total": 20,
        "defaults": {
            "optimization_config": config,
            "autonomous_workflow": {"active_fidelity": "F2"},
        },
    }


def _experiment(code: str, *, warm_start: str | None = None) -> dict:
    backend = {"F0": "python", "F1": "python", "F2": "python3d", "F3": "matlab"}[code]
    mesh = {"F0": "coarse", "F1": "coarse", "F2": "coarse3d", "F3": "fine3d"}[code]
    return {
        "id": f"E-{code}",
        "purpose": f"Test {code}",
        "fidelity": f"{code} — test",
        "backend": backend,
        "mesh_level": mesh,
        "warm_start": warm_start,
        "parameters": {
            "volfrac": 0.35,
            "beta": 4.0,
            "move": 0.1,
            "penal": 1.0,
            "rmin": 4.0,
            "min_iter": 1,
            "max_iter": 999,
            "accuracy": "standard",
            "filter_strategy": "fixed",
            "grid3d": [3, 3, 3],
        },
    }


def test_stage_decision_request_accepts_action_and_legacy_boolean() -> None:
    assert FidelityStageDecisionRequest(action="REPEAT_STAGE").action == "REPEAT_STAGE"
    assert FidelityStageDecisionRequest(advance=False).advance is False
    with pytest.raises(ValueError):
        FidelityStageDecisionRequest()


def test_stage_decision_api_repeat_keeps_the_same_fidelity(monkeypatch, tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(fastapi_app, "service", service)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    try:
        created = service.create_research({"name": "A", "goal": "B", "mode": "AUTONOMOUS"})
        service.store.append_event(
            created["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F2 complete",
            payload={
                "stage_code": "F2", "internal_fidelity": "F2", "round": 1,
                "experiment_ids": [], "result": {"successful": 0, "failed": 0},
            },
        )
        response = TestClient(fastapi_app.app).post(
            f"/api/research/{created['id']}/fidelity-stage-decision",
            json={"action": "REPEAT_STAGE"},
        )
        assert response.status_code == 200, response.text
        workflow = (service.get_research(created["id"]).get("defaults") or {})[
            "autonomous_workflow"
        ]
        assert workflow["active_fidelity"] == "STEP3"
        duplicate = TestClient(fastapi_app.app).post(
            f"/api/research/{created['id']}/fidelity-stage-decision",
            json={"action": "ADVANCE_STAGE"},
        )
        assert duplicate.status_code == 409
    finally:
        service.close()


def test_new_research_defaults_and_identifier_are_not_mbb(tmp_path) -> None:
    defaults = ResearchCreate()
    assert "mbb" not in defaults.name.lower()
    assert str(defaults.geometry.get("type", "")).lower() != "mbb"
    assert str(defaults.boundary_conditions.get("type", "")).lower() != "mbb"
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        assert service.create_research({"name": "A", "goal": "B"})["id"] == "R-001"
    finally:
        service.close()


def test_agent_memory_exposes_authoritative_configuration_and_stage() -> None:
    research = _research_state()
    memory = ResearchMemory().build(research, [], [], [])
    l3 = memory["L3"]
    assert l3["authoritative_optimization_config"] == _optimization_config()
    assert l3["active_fidelity"] == "STEP3"
    assert l3["deep_optimization_mutable_parameters"] == [
        "volfrac", "beta", "beta_max", "projection", "controller", "move",
    ]
    assert "bcType" in l3["immutable_visible_parameters"]
    assert "penal" in l3["immutable_visible_parameters"]


def test_config_template_derives_all_fields_from_research_state(monkeypatch, tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", service)
    try:
        created = service.create_research({
            "name": "Configured",
            "goal": "Configured",
            "geometry": {
                "dimension": "3d", "dimensions": [9.0, 3.0, 2.0], "unit": "cm",
                "cell_size_m": 0.01, "nelx": 90, "nely": 30, "nelz": 20,
                "accuracy": "high",
            },
            "material": {
                "preset": "steel", "name": "Steel", "E_GPa": 210.0, "nu": 0.29,
                "density_kg_m3": 7850.0, "yield_strength_MPa": 355.0,
            },
            "boundary_conditions": {"type": "simply_supported"},
            "constraints": {"volume_fraction": 0.31, "gray_max": 0.05, "connected": True},
        })
        current = service.get_research(created["id"])
        defaults = dict(current.get("defaults") or {})
        defaults["experiment"] = {"parameters": {
            "penal": 3.5, "rmin": 2.2, "min_iter": 25, "max_iter": 140,
            "filter_strategy": "adaptive",
        }}
        service.store.update_research_json(created["id"], defaults=defaults)
        config, persisted = research_router._research_config_template(created["id"])
        assert persisted is False
        assert config.bcType == "simply_supported"
        assert config.volfrac == pytest.approx(0.31)
        assert config.penal == pytest.approx(3.5)
        assert config.rmin == pytest.approx(2.2)
        assert config.minIterations == 25
        assert config.maxIterations == 140
        assert config.filterStrategy == "adaptive"
        assert config.material.youngsModulusGPa == pytest.approx(210.0)
    finally:
        service.close()


@pytest.mark.parametrize(
    ("code", "expected_grid", "expected_2d"),
    [
        ("F0", None, (12, 4)),
        ("F1", None, (18, 6)),
        ("F2", [12, 4, 3], None),
        ("F3", [24, 8, 6], None),
    ],
)
def test_solver_task_uses_stage_grid_and_locks_visible_config(code, expected_grid, expected_2d) -> None:
    task = build_solver_task(_experiment(code), _research_state())
    params = task["params"]
    assert task["load_case"] == "L-bracket"
    assert params["volfrac"] == pytest.approx(0.35)
    assert params["penal"] == pytest.approx(3.2)
    assert params["rmin"] == pytest.approx(2.0)
    assert params["min_iter"] == 30
    assert params["max_iter"] == 120
    assert params["accuracy"] == "high"
    assert params["filter_strategy"] == "adaptive"
    assert params["E"] == pytest.approx(68.9)
    assert params["nu"] == pytest.approx(0.33)
    if expected_grid is not None:
        assert params["grid3d"] == expected_grid
    else:
        assert (params["nelx"], params["nely"]) == expected_2d


def test_f3_warm_start_remains_a_full_matlab_optimization(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    try:
        service.store.create_research(research)
        service.store.create_experiment({
            **_experiment("F2"), "id": "E01", "research_id": research["id"],
            "status": "SUCCESS", "round_number": 1,
        })
        density = [[[0.4 for _ in range(12)] for _ in range(4)] for _ in range(3)]
        service.store.update_experiment("E01", result={"artifacts": {"density": density}})
        f3 = {
            **_experiment("F3", warm_start="E01"), "id": "E02",
            "research_id": research["id"], "status": "RUNNING", "round_number": 2,
        }
        task, _, _ = service._prepare_claimed_experiment(f3, research)
        warm = task["params"]["initial_density"]
        assert (len(warm), len(warm[0]), len(warm[0][0])) == (4, 12, 3)
        assert "verification_mode" not in task["params"]
        assert task["params"]["grid3d"] == [24, 8, 6]
    finally:
        service.close()


def test_matlab_f3_config_preserves_visible_iterations_accuracy_and_filter() -> None:
    config = MatlabMcpWorker._config(build_solver_task(_experiment("F3"), _research_state()), 3)
    assert config["max_iterations"] == 120
    assert config["min_iterations"] == 30
    assert config["accuracy"] == "high"
    assert config["filter_strategy"] == "adaptive"
    assert config["nelx"] == 24 and config["nely"] == 8 and config["nelz"] == 6


def test_matlab_f3_config_preserves_allowed_hidden_controls() -> None:
    experiment = _experiment("F3")
    experiment["parameters"].update({
        "beta": 2.0, "beta_max": 8.0, "projection": "none",
        "controller": "fixed_controller", "move": 0.075,
    })
    config = MatlabMcpWorker._config(build_solver_task(experiment, _research_state()), 3)
    assert config["beta"] == 2.0
    assert config["beta_max"] == 8.0
    assert config["projection"] == "none"
    assert config["controller"] == "fixed_controller"
    assert config["move_start"] == pytest.approx(0.075)
    assert config["move_end"] == pytest.approx(0.075)


def test_changed_volume_fraction_is_evaluated_against_the_experiment_target() -> None:
    result = {
        "status": "converged", "objective": {"compliance": 1.0},
        "constraints": {"volume_fraction": 0.35},
        "quality": {"gray_ratio": 0.01, "connected_components": 1},
    }
    analysis = ResearchOrchestrator().analyze(
        {"constraints": {"volume_fraction": 0.4, "gray_max": 0.05, "connected": True}},
        result,
        {"parameters": {"volfrac": 0.35}},
    )
    assert analysis["evaluation"]["checks"]["volume"] is True
    assert analysis["evaluation"]["volume_error"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("load_case", "canonical"),
    [
        ("MBB", "MBB"),
        ("cantilever", "cantilever"),
        ("simply_supported", "simply_supported"),
        ("L-bracket", "L-bracket"),
    ],
)
def test_python_f2_supports_every_visible_3d_load_case(load_case, canonical) -> None:
    fixed, force, actual = _boundary_conditions_3d(6, 4, 2, load_case, 2.5)
    assert actual == canonical
    assert fixed.size > 0
    assert (force == -2.5).sum() == 1
    assert (force != 0).sum() == 1


def test_user_can_finish_without_a_step4_parameter_match_gate(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    try:
        service.store.create_research(research)
        for index, code in enumerate(("F0", "F1", "F2")):
            stage_result = {"objective": {"compliance": 2.0},
                            "constraints": {"volume_fraction": 0.35},
                            "quality": {"gray_ratio": 0.01, "connected_components": 1}}
            service.store.create_experiment({
                **_experiment(code), "id": f"E0{index + 1}", "research_id": research["id"],
                "status": "SUCCESS", "round_number": index + 1,
            })
            service.store.update_experiment(f"E0{index + 1}", result=stage_result)
        experiment = {
            **_experiment("F3", warm_start="E03"), "id": "E04", "research_id": research["id"],
            "status": "SUCCESS", "round_number": 1,
        }
        task = build_solver_task(experiment, research)
        result = {
            "objective": {"compliance": 1.0},
            "constraints": {"volume_fraction": 0.35},
            "quality": {"gray_ratio": 0.01, "connected_components": 1},
            "solver": {
                "backend": "matlab_mcp_3d",
                "executed_config": MatlabMcpWorker._config(task, 3),
            },
        }
        service.store.create_experiment(experiment)
        service.store.update_experiment("E04", result=result)
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F3 complete",
            payload={
                "stage_code": "F3", "internal_fidelity": "F3", "round": 1,
                "experiment_ids": ["E04"], "result": {"successful": 1, "failed": 0},
            },
        )
        tampered = {**result, "solver": {**result["solver"], "executed_config": {
            **result["solver"]["executed_config"], "move_start": 0.5,
        }}}
        service.store.update_experiment("E04", result=tampered)
        approved = service.decide_fidelity_stage(research["id"], "APPROVE_FINAL")
        assert approved["status"] == "STOPPED"
        assert approved["termination_reason"] == "USER_FINISHED"
        preview = service.report_preview(research["id"])
        assert "不能宣称设计成功" in preview["markdown"]
    finally:
        service.close()


def test_autonomous_f2_success_cannot_terminate_before_f3_approval(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        created = service.create_research({
            "name": "Workflow", "goal": "Workflow", "mode": "AUTONOMOUS",
            "constraints": {
                "volume_fraction": 0.4, "gray_max": 0.05,
                "connected": True, "required_fidelity": "F2",
            },
        })
        service.store.create_experiment({
            **_experiment("F2"), "id": "E01", "research_id": created["id"],
            "status": "SUCCESS", "round_number": 1,
            "result": {
                "objective": {"compliance": 1.0},
                "constraints": {"volume_fraction": 0.4},
                "quality": {"gray_ratio": 0.01, "connected_components": 1},
            },
        })
        assert service._termination_reason(created["id"]) is None
    finally:
        service.close()


def test_autonomous_budget_exhaustion_waits_instead_of_ending(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        created = service.create_research({
            "name": "Budget guard", "goal": "Reach approved F3", "mode": "AUTONOMOUS",
            "budget_total": 1,
            "budgets": {"total": 1, "f0": 1, "f1": 0, "f2": 0, "f3": 0},
        })
        service.store.create_experiment({
            **_experiment("F0"), "id": "E01", "research_id": created["id"],
            "status": "SUCCESS", "round_number": 1,
            "result": {
                "objective": {"compliance": 1.0},
                "constraints": {"volume_fraction": 0.4},
                "quality": {"gray_ratio": 0.01, "connected_components": 1},
            },
        })
        service.store.update_experiment("E01", run_id="budget-run")

        service._safe_mode_next(created["id"])

        state = service.get_research(created["id"])
        assert state["status"] == "READY"
        assert state["termination_reason"] is None
        assert not any("BUDGET_AWAITING_ACTION" in event["title"] for event in state["events"])
    finally:
        service.close()


def test_autonomous_f3_repeat_is_not_blocked_by_the_per_stage_budget(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    research["budget_total"] = 1
    research["budgets"] = {"total": 1, "f0": 0, "f1": 0, "f2": 0, "f3": 1}
    try:
        service.store.create_research(research)
        service.store.create_experiment({
            **_experiment("F3"), "id": "E01", "research_id": research["id"],
            "status": "SUCCESS", "round_number": 1,
        })
        service.store.update_experiment("E01", run_id="first-f3")
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F3 complete",
            payload={"stage_code": "F3", "internal_fidelity": "F3", "round": 1,
                     "experiment_ids": ["E01"], "result": {"successful": 1, "failed": 0}},
        )
        service._send_pi_or_fallback = lambda *_args: None

        decided = service.decide_fidelity_stage(research["id"], "REPEAT_STAGE")
        assert decided["budget_total"] == 1
        assert decided["budgets"]["total"] == 1
        assert decided["budgets"]["f3"] == 1

        repeated = service.create_experiment(research["id"], {
            **_experiment("F3"), "id": "ignored", "purpose": "Repeat F3",
        })
        assert repeated["fidelity"].startswith("Step4")
    finally:
        service.close()


def test_autonomous_f3_repeat_extends_exhausted_lane_with_total_remaining(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    research["budget_total"] = 5
    research["budgets"] = {"total": 5, "f0": 0, "f1": 0, "f2": 0, "f3": 1}
    try:
        service.store.create_research(research)
        service.store.create_experiment({
            **_experiment("F3"), "id": "E01", "research_id": research["id"],
            "status": "SUCCESS", "round_number": 1,
        })
        service.store.update_experiment("E01", run_id="first-f3")
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F3 complete",
            payload={"stage_code": "F3", "internal_fidelity": "F3", "round": 1,
                     "experiment_ids": ["E01"], "result": {"successful": 1, "failed": 0}},
        )
        service._send_pi_or_fallback = lambda *_args: None

        decided = service.decide_fidelity_stage(research["id"], "REPEAT_STAGE")

        assert decided["budget_total"] == 5
        assert decided["budgets"]["total"] == 5
        assert decided["budgets"]["f3"] == 1
        repeated = service.create_experiment(research["id"], {
            **_experiment("F3"), "id": "ignored", "purpose": "Repeat F3",
        })
        assert repeated["fidelity"].startswith("Step4")
    finally:
        service.close()


def test_legacy_stage_budget_no_longer_blocks_human_controlled_experiments(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    # This test isolates legacy budget compatibility outside an active
    # autonomous run; active runs are separately protected by one-shot tokens.
    research["defaults"].pop("autonomous_workflow")
    research["budgets"] = {"total": 20, "f0": 6, "f1": 6, "f2": 0, "f3": 4}
    try:
        service.store.create_research(research)
        experiment = service.create_experiment(research["id"], _experiment("F2"))
        assert experiment["fidelity"].startswith("Step3")
    finally:
        service.close()


def test_advance_to_f3_authorizes_one_run_when_f3_lane_is_empty(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    research["budgets"] = {"total": 20, "f0": 6, "f1": 6, "f2": 4, "f3": 0}
    try:
        service.store.create_research(research)
        stage_result = {
            "objective": {"compliance": 1.0},
            "constraints": {"volume_fraction": 0.4},
            "quality": {"gray_ratio": 0.01, "connected_components": 1},
        }
        service.store.create_experiment({
            **_experiment("F2"), "id": "E01", "research_id": research["id"],
            "status": "SUCCESS", "round_number": 1,
        })
        service.store.update_experiment("E01", result=stage_result)
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F2 complete",
            payload={"stage_code": "F2", "internal_fidelity": "F2", "round": 1,
                     "experiment_ids": ["E01"], "result": {"successful": 1, "failed": 0}},
        )
        service._send_pi_or_fallback = lambda *_args: None

        decided = service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")

        assert decided["budgets"]["f3"] == 0
        assert decided["defaults"]["autonomous_workflow"]["active_fidelity"] == "STEP4"
        experiment = service.create_experiment(research["id"], _experiment("F3"))
        assert experiment["fidelity"].startswith("Step4")
    finally:
        service.close()


def test_step4_requires_a_stage_authorization_instead_of_a_pre_run_decision(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    research["budgets"] = {"total": 5, "f0": 0, "f1": 0, "f2": 0, "f3": 1}
    try:
        service.store.create_research(research)
        with pytest.raises(ValueError, match="unconsumed human authorization"):
            service.create_experiment(research["id"], _experiment("F3"))
    finally:
        service.close()


def test_legacy_total_budget_no_longer_reserves_or_blocks_slots(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    # Historical/manual records may still be created without a run token; the
    # legacy count fields must not become an implicit limit.
    research["defaults"].pop("autonomous_workflow")
    research["budget_total"] = 1
    research["budgets"] = {"total": 1, "f0": 0, "f1": 0, "f2": 0, "f3": 2}
    try:
        service.store.create_research(research)
        first = service.create_experiment(research["id"], _experiment("F0"))
        assert first["status"] == "WAITING"
        second = service.create_experiment(research["id"], _experiment("F0"))
        assert second["status"] == "WAITING"
    finally:
        service.close()


def test_failed_stage_cannot_advance(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    research = _research_state()
    try:
        service.store.create_research(research)
        service.store.create_experiment({
            **_experiment("F2"), "id": "E01", "research_id": research["id"],
            "status": "FAILED", "round_number": 1, "error": "solver failed",
        })
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "F2 failed",
            payload={"stage_code": "F2", "internal_fidelity": "F2", "round": 1,
                     "experiment_ids": ["E01"], "result": {"successful": 0, "failed": 1}},
        )

        with pytest.raises(ValueError, match="没有有效真实结果"):
            service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        assert service._pending_fidelity_stage_gate(research["id"]) is not None
    finally:
        service.close()


@pytest.mark.parametrize("with_completed", [False, True])
def test_safe_mode_no_proposal_waits_instead_of_ending(tmp_path, with_completed) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        created = service.create_research({
            "name": "No proposal", "goal": "Reach approved F3", "mode": "AUTONOMOUS",
        })
        if with_completed:
            stage_result = {"objective": {"compliance": 1.0},
                            "constraints": {"volume_fraction": 0.4},
                            "quality": {"gray_ratio": 0.01, "connected_components": 1}}
            service.store.create_experiment({
                **_experiment("F0"), "id": "E01", "research_id": created["id"],
                "status": "SUCCESS", "round_number": 1,
            })
            service.store.update_experiment("E01", result=stage_result)
        service.tools.policy_compile_intent = lambda *_args, **_kwargs: []

        service._safe_mode_next(created["id"])

        state = service.get_research(created["id"])
        assert state["status"] == "READY"
        assert state["termination_reason"] is None
        assert any(event["title"] == "DEEP_OPTIMIZATION_PLAN_AWAITING_ACTION"
                   for event in state["events"])
    finally:
        service.close()


def test_safe_mode_submit_failure_waits_instead_of_staying_running(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        created = service.create_research({
            "name": "Rejected proposal", "goal": "Reach approved F3", "mode": "AUTONOMOUS",
        })
        service.store.create_experiment({
            **_experiment("F0"), "id": "E01", "research_id": created["id"],
            "status": "SUCCESS", "round_number": 1,
        })
        service.store.update_experiment("E01", result={
            "objective": {"compliance": 1.0},
            "constraints": {"volume_fraction": 0.4},
            "quality": {"gray_ratio": 0.01, "connected_components": 1},
        })
        service.tools.policy_compile_intent = lambda *_args, **_kwargs: [{"id": "P01"}]
        service.submit_proposal = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("proposal rejected"))

        service._safe_mode_next(created["id"])

        state = service.get_research(created["id"])
        assert state["status"] == "READY"
        assert state["termination_reason"] is None
        assert any(event["title"] == "DEEP_OPTIMIZATION_PLAN_AWAITING_ACTION"
                   for event in state["events"])
    finally:
        service.close()


def test_solver_capabilities_report_python_then_matlab(tmp_path) -> None:
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        service.matlab_worker.health = lambda: {"state": "UNAVAILABLE"}
        service.matlab_worker.capabilities = lambda probe=False: {"variants": ["reference_cpu"]}
        profiles = {item["fidelity"]: item for item in service.solver_capabilities()["fidelities"]}
        assert profiles["STEP1"]["backend"] == "python" and profiles["STEP1"]["available"] is True
        assert profiles["STEP2"]["backend"] == "python" and profiles["STEP2"]["available"] is True
        assert profiles["STEP3"]["backend"] == "python3d" and profiles["STEP3"]["available"] is True
        assert profiles["STEP4"]["backend"] == "matlab" and profiles["STEP4"]["available"] is False
    finally:
        service.close()
