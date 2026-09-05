import threading
import sqlite3

import pytest

from topoptpilot.evaluator.evaluator import evaluate_result
from topoptpilot.fidelity.manager import FidelityManager
from topoptpilot.nomenclature import normalize_mode, normalize_stage, stage_label
from topoptpilot.schemas import Fidelity, ResearchCreate
from topoptpilot.service import ResearchService

def _experiment(step: str) -> dict:
    return {"purpose": step, "fidelity": stage_label(step),
            "mesh_level": FidelityManager.mesh_level(step),
            "backend": FidelityManager.backend_for(step),
            "parameters": {"volfrac": .4, "penal": 3., "rmin": 1.5, "max_iter": 2}}

def test_converged_result_is_success_even_when_targets_unmet():
    result = {"status": "converged", "objective": {"compliance": 687.2},
              "constraints": {"volume_fraction": .4},
              "quality": {"gray_ratio": .93, "connected_components": 3}}
    evaluation = evaluate_result(result, {"volume_fraction": .4, "gray_max": .05, "connected": True})
    assert evaluation["success"] is True, "求解收敛且指标完备即为成功"
    assert evaluation["feasible"] is False, "契约阈值未满足只记为目标差距"
    assert evaluation["unmet_targets"] == ["gray", "connected"]
    assert evaluation["next_action"] == "RESTORE_CONNECTIVITY"

def test_solver_failure_stays_invalid():
    result = {"status": "failed", "objective": {}, "constraints": {}, "quality": {}}
    evaluation = evaluate_result(result, {"volume_fraction": .4})
    assert evaluation["success"] is False and evaluation["feasible"] is False
    assert evaluation["next_action"] == "RETRY_OR_REVISE"

def test_targets_met_result_is_feasible():
    result = {"status": "converged", "objective": {"compliance": .44},
              "constraints": {"volume_fraction": .4},
              "quality": {"gray_ratio": .017, "connected_components": 1}}
    evaluation = evaluate_result(result, {"volume_fraction": .4, "gray_max": .05, "connected": True})
    assert evaluation["success"] is True and evaluation["feasible"] is True
    assert evaluation["unmet_targets"] == []
    assert evaluation["next_action"] == "PROMOTE_OR_REPORT"

def test_new_names_are_canonical_and_legacy_names_are_accepted():
    assert [item.value for item in Fidelity] == ["STEP1", "STEP2", "STEP3", "STEP4"]
    assert normalize_stage("F2 — Python 3D Coarse") == "STEP3"
    assert normalize_mode("AUTONOMOUS") == "DEEP_OPTIMIZATION"
    assert ResearchCreate(name="A", goal="B", mode="AUTONOMOUS").mode == "DEEP_OPTIMIZATION"

def test_deep_optimization_can_compile_the_step1_baseline(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Baseline","goal":"Begin","mode":"DEEP_OPTIMIZATION"})
        proposals = service.tools.policy_compile_intent(
            research["id"], intent="ESTABLISH_BASELINE", _decision_source="RULE_FALLBACK"
        )
        assert len(proposals) == 1
        assert proposals[0]["fidelity"] == "STEP1"
        assert proposals[0]["controlled_factors"] == ["baseline"]
    finally: service.close()

def test_count_budget_does_not_block_human_controlled_steps(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Unlimited","goal":"Human controlled","mode":"DEEP_OPTIMIZATION","budget_total":1,"budgets":{"total":1,"f0":0,"f1":0,"f2":0,"f3":0}})
        first = service.create_experiment(research["id"], _experiment("STEP1"))
        second = service.create_experiment(research["id"], _experiment("STEP1"))
        assert first["fidelity"].startswith("Step1") and second["fidelity"].startswith("Step1")
    finally: service.close()

def test_step4_has_no_separate_pre_run_approval(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"One gate","goal":"Finish","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP3"),"id":"E01","research_id":research["id"],"status":"SUCCESS","round_number":1})
        service.store.update_experiment("E01", result={"objective":{"compliance":1.},"constraints":{"volume_fraction":.4},"quality":{"gray_ratio":.01,"connected_components":1},"artifacts":{"density":[[[1.]]],"history":[{"iteration":1,"compliance":1.}]}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step3 complete",payload={"stage_code":"STEP3","internal_fidelity":"STEP3","round":1,"experiment_ids":["E01"],"best_experiment_id":"E01","result":{"successful":1,"failed":0}})
        service._send_pi_or_fallback = lambda *_args: None
        service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        experiment = service.create_experiment(research["id"], _experiment("STEP4"))
        assert experiment.get("decision_id") is None
    finally: service.close()

def test_unideal_but_valid_result_can_advance(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Choice","goal":"Very low compliance","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP1"),"id":"E01","research_id":research["id"],"status":"SUCCESS","round_number":1})
        service.store.update_experiment("E01", result={"objective":{"compliance":999.},"constraints":{"volume_fraction":.4},"quality":{"gray_ratio":.9,"connected_components":2},"artifacts":{"density":[[1.]],"history":[{"iteration":1,"compliance":999.}]}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step1 complete",payload={"stage_code":"STEP1","internal_fidelity":"STEP1","round":1,"experiment_ids":["E01"],"best_experiment_id":"E01","result":{"successful":1,"failed":0}})
        service._send_pi_or_fallback = lambda *_args: None
        decided = service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        assert decided["defaults"]["autonomous_workflow"]["active_fidelity"] == "STEP2"
    finally: service.close()

def test_step4_authorization_is_consumed_exactly_once_under_concurrency(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Atomic","goal":"One Step4","mode":"DEEP_OPTIMIZATION"})
        defaults = dict(research.get("defaults") or {})
        defaults["autonomous_workflow"] = {"active_fidelity":"STEP4", "step_authorization":{"stage":"STEP4","gate_event_id":"7","consumed":False,"authorized_by":"ADVANCE_STAGE"}}
        service.store.update_research_json(research["id"], defaults=defaults)
        created=[]; errors=[]
        def create():
            try: created.append(service.create_experiment(research["id"], _experiment("STEP4")))
            except Exception as exc: errors.append(exc)
        threads=[threading.Thread(target=create) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert len(created) == 1 and len(errors) == 1
        assert "unconsumed human authorization" in str(errors[0])
    finally: service.close()

def test_step1_authorization_covers_a_three_direction_round(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Compare","goal":"Human controlled","hypothesis":"三个方向会产生可比较证据","mode":"DEEP_OPTIMIZATION"})
        planned = service.start_autonomous_research(research["id"])
        plan = planned["defaults"]["autonomous_workflow"]["candidate_plan"]
        assert len(plan["proposal_ids"]) == 3
        assert service.store.list_experiments(research["id"]) == []
        service.confirm_candidate_plan(research["id"], plan["recommended_proposal_id"])
        created = service.store.list_experiments(research["id"])
        assert all(item["fidelity"].startswith("Step1") for item in created)
        try:
            service.create_experiment(research["id"], _experiment("STEP1"))
        except ValueError as exc:
            assert "候选名额已用完" in str(exc)
        else:
            raise AssertionError("a single human authorization created more than three Step1 candidates")
    finally: service.close()

def test_failed_result_with_partial_metrics_cannot_advance(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Coarse","goal":"Screen first","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP1"),"id":"E01","research_id":research["id"],"status":"FAILED","round_number":1})
        service.store.update_experiment("E01", result={"objective":{"compliance":3.99},"constraints":{"volume_fraction":.4},"quality":{"gray_ratio":.93,"connected_components":2},"artifacts":{"density":[[1.]],"history":[{"iteration":1,"compliance":3.99}]}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step1 complete",payload={"stage_code":"STEP1","internal_fidelity":"STEP1","round":1,"experiment_ids":["E01"],"best_experiment_id":None,"result":{"successful":0,"failed":1}})
        service._send_pi_or_fallback = lambda *_args: None
        with pytest.raises(ValueError, match="没有有效真实结果"):
            service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        decided = service.decide_fidelity_stage(research["id"], "REPEAT_STAGE")
        assert decided["defaults"]["autonomous_workflow"]["active_fidelity"] == "STEP1"
    finally: service.close()

def test_advance_blocked_until_a_usable_result_exists(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Infra","goal":"No metrics yet","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP1"),"id":"E01","research_id":research["id"],"status":"FAILED","round_number":1,"error":"solver crashed"})
        service.store.update_experiment("E01", result={"status":"failed","objective":{},"constraints":{},"quality":{},"artifacts":{}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step1 infra failure",payload={"stage_code":"STEP1","internal_fidelity":"STEP1","round":1,"experiment_ids":["E01"],"best_experiment_id":None,"result":{"successful":0,"failed":1}})
        service._send_pi_or_fallback = lambda *_args: None
        try:
            service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        except ValueError as exc:
            assert "没有有效真实结果" in str(exc)
        else:
            raise AssertionError("advance must require a usable real result")
        decided = service.decide_fidelity_stage(research["id"], "REPEAT_STAGE")
        assert decided["defaults"]["autonomous_workflow"]["active_fidelity"] == "STEP1"
    finally: service.close()

def test_safe_mode_submits_three_directions_in_round_one(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Three","goal":"Compare directions","mode":"DEEP_OPTIMIZATION"})
        defaults = dict(research.get("defaults") or {})
        defaults["autonomous_workflow"] = {
            "active_fidelity": "STEP1",
            "step_authorization": {"stage": "STEP1", "gate_event_id": "1", "consumed": False,
                                    "authorized_by": "START_DEEP_OPTIMIZATION",
                                    "candidates_limit": 3, "experiment_ids": []},
        }
        service.store.update_research_json(research["id"], defaults=defaults)
        service._safe_mode_next(research["id"])
        experiments = service.store.list_experiments(research["id"])
        assert len(experiments) == 3
        keys = {tuple(sorted((k, repr(v)) for k, v in item["parameters"].items()
                             if k != "initial_density")) for item in experiments}
        assert len(keys) == 3
    finally: service.close()

def test_safe_mode_cannot_run_without_a_human_step_authorization(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"No auth","goal":"Wait","mode":"DEEP_OPTIMIZATION"})
        service._safe_mode_next(research["id"])
        state = service.get_research(research["id"])
        assert state["status"] == "READY"
        assert state["experiments"] == []
        assert any("没有未消费的人工 Step 授权" in event["body"] for event in state["events"])
    finally: service.close()

def test_compile_dedup_matches_normalized_history(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Dedup","goal":"No repeat runs","mode":"DEEP_OPTIMIZATION"})
        # 按求解任务规范化后的完整参数形态存储（真实 E185 同款），含材料等附加键
        stored = {"volfrac": .4, "beta": 1.0, "beta_max": 2.0, "projection": "none",
                  "controller": "fixed_controller", "move": 0.1, "penal": 3.0, "rmin": 1.5,
                  "max_iter": 80, "min_iter": 10, "filter_strategy": "fixed",
                  "E": 200.0, "nu": .3, "name": "结构钢", "preset": "structural-steel"}
        service.store.create_experiment({**_experiment("STEP1"), "id": "E01",
            "research_id": research["id"], "status": "FAILED", "round_number": 1,
            "parameters": stored})
        service.store.update_experiment("E01", result={"objective": {"compliance": 687.2},
            "constraints": {"volume_fraction": .4},
            "quality": {"gray_ratio": .93, "connected_components": 3}, "artifacts": {}})
        proposals = service.tools.policy_compile_intent(
            research["id"], intent="RESTORE_CONNECTIVITY", source_experiment="E01",
            _decision_source="RULE_FALLBACK")
        duplicate = [p for p in proposals
                     if service.tools.compiler.canonical_parameter_key(p["parameters"])
                     == service.tools.compiler.canonical_parameter_key(stored)]
        assert not duplicate, "编译器不得重复提出已运行过的规范化配置"
    finally: service.close()

def test_round_best_prefers_connectivity_then_grayness_then_compliance():
    disconnected_stiff = {"id": "E01", "result": {"objective": {"compliance": 1.0},
        "quality": {"gray_ratio": .10, "connected_components": 2}}}
    connected_gray = {"id": "E02", "result": {"objective": {"compliance": 5.0},
        "quality": {"gray_ratio": .20, "connected_components": 1}}}
    connected_best = {"id": "E03", "result": {"objective": {"compliance": 2.0},
        "quality": {"gray_ratio": .05, "connected_components": 1}}}
    best = ResearchService._select_round_best([disconnected_stiff, connected_gray, connected_best])
    assert best["id"] == "E03"
    tied = ResearchService._select_round_best([connected_gray, disconnected_stiff])
    assert tied["id"] == "E02"

def test_advance_uses_round_best_as_baseline_and_repeat_starts_fresh(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Base","goal":"灰度尽可能低","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP1"),"id":"E01","research_id":research["id"],
            "status":"SUCCESS","round_number":1,
            "parameters":{"volfrac":.4,"beta":2.0,"penal":3.,"rmin":1.5,"max_iter":2}})
        service.store.update_experiment("E01", result={"objective":{"compliance":3.4},
            "constraints":{"volume_fraction":.4},
            "quality":{"gray_ratio":.93,"connected_components":3},"artifacts":{}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step1 complete",
            payload={"stage_code":"STEP1","internal_fidelity":"STEP1","round":1,
                     "experiment_ids":["E01"],"best_experiment_id":"E01",
                     "result":{"successful":1,"failed":0}})
        decided = service.decide_fidelity_stage(research["id"], True)
        authorization = decided["defaults"]["autonomous_workflow"]["step_authorization"]
        assert authorization["stage"] == "STEP2"
        assert authorization["baseline_experiment_id"] == "E01"
        # 推进后的回退规划必须从最优方案派生三套单因子候选
        service._safe_mode_next(research["id"])
        derived = [e for e in service.store.list_experiments(research["id"]) if e["id"] != "E01"]
        assert len(derived) == 3
        assert all((e.get("intent_source") or e.get("decision_source")) for e in derived)
        assert all(e["fidelity"].startswith("Step2") for e in derived)
        # REPEAT：回到 STEP1 且不带基线 → 重新生成全新对比方案
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step2 complete",
            payload={"stage_code":"STEP2","internal_fidelity":"STEP2","round":2,
                     "experiment_ids":["E02"],"best_experiment_id":None,
                     "result":{"successful":0,"failed":0}})
        repeated = service.decide_fidelity_stage(research["id"], False)
        repeat_authorization = repeated["defaults"]["autonomous_workflow"]["step_authorization"]
        assert repeat_authorization["stage"] == "STEP2"
        assert not repeat_authorization["baseline_experiment_id"]
    finally: service.close()

def test_step4_round_inherits_baseline_parameters_verbatim(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Inherit","goal":"高精度复核","mode":"DEEP_OPTIMIZATION"})
        defaults = dict(research.get("defaults") or {})
        defaults["optimization_config"] = {"rmin": 2.0, "penal": 3.0, "maxIterations": 80,
                                           "minIterations": 10, "filterStrategy": "fixed"}
        service.store.update_research_json(research["id"], defaults=defaults)
        baseline_params = {"volfrac":.4,"beta":32.0,"beta_max":64.0,
                           "projection":"heaviside_projection","controller":"periodic_controller",
                           "move":.1,"penal":3.,"rmin":2.,"max_iter":80,"min_iter":10,
                           "filter_strategy":"fixed"}
        service.store.create_experiment({**_experiment("STEP3"),"id":"E01","research_id":research["id"],
            "status":"SUCCESS","round_number":3,"parameters":baseline_params})
        service.store.update_experiment("E01", result={"objective":{"compliance":.18},
            "constraints":{"volume_fraction":.4},
            "quality":{"gray_ratio":.559,"connected_components":1},"artifacts":{}})
        service.store.append_event(research["id"],"HUMAN","FIDELITY_STAGE_AWAITING_DECISION","Step3 complete",
            payload={"stage_code":"STEP3","internal_fidelity":"STEP3","round":3,
                     "experiment_ids":["E01"],"best_experiment_id":"E01",
                     "result":{"successful":1,"failed":0}})
        service.decide_fidelity_stage(research["id"], "ADVANCE_STAGE")
        service._safe_mode_next(research["id"])
        matlab_runs = [e for e in service.store.list_experiments(research["id"]) if e["backend"] == "matlab"]
        assert len(matlab_runs) == 1
        step4 = matlab_runs[0]
        assert step4["fidelity"].startswith("Step4")
        assert step4.get("warm_start") == "E01"
        from topoptpilot.policy.intent_compiler import IntentCompiler
        assert (IntentCompiler.canonical_parameter_key(step4["parameters"])
                == IntentCompiler.canonical_parameter_key(baseline_params))
    finally: service.close()

def test_reduce_grayness_keeps_beta_max_consistent(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"Beta","goal":"升β受控","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP1"),"id":"E01","research_id":research["id"],
            "status":"SUCCESS","round_number":1,
            "parameters":{"volfrac":.4,"beta":4.0,"beta_max":2.0,"penal":3.,"rmin":1.5,"max_iter":2}})
        service.store.update_experiment("E01", result={"objective":{"compliance":1.},
            "constraints":{"volume_fraction":.4},
            "quality":{"gray_ratio":.5,"connected_components":1},"artifacts":{}})
        proposals = service.tools.policy_compile_intent(
            research["id"], intent="REDUCE_GRAYNESS", source_experiment="E01",
            _decision_source="RULE_FALLBACK")
        assert proposals, "应有继续升β的候选"
        params = proposals[0]["parameters"]
        assert params["beta"] > 4.0
        assert params["beta_max"] >= params["beta"], "beta_max 必须随 beta 抬升，否则 MATLAB 信封拒绝"
        assert params["beta_max"] == 64.0, "降低灰度候选必须使用安全信封内的完整锐化空间"
    finally: service.close()

def test_start_resumes_unconsumed_step4_authorization(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    monkeypatch.setattr(service, "run_experiment", lambda _id: None)
    try:
        research = service.create_research({"name":"Resume","goal":"从Step4恢复","hypothesis":"Step4 会复核 Step3 基线","mode":"DEEP_OPTIMIZATION"})
        defaults = dict(research.get("defaults") or {})
        defaults["autonomous_workflow"] = {"active_fidelity":"STEP4",
            "step_authorization":{"stage":"STEP4","gate_event_id":"3","consumed":False,
                                  "authorized_by":"ADVANCE_STAGE","candidates_limit":1,
                                  "experiment_ids":[],"baseline_experiment_id":"E01"}}
        service.store.update_research_json(research["id"], defaults=defaults)
        state = service.start_autonomous_research(research["id"])
        workflow = state["defaults"]["autonomous_workflow"]
        assert workflow["active_fidelity"] == "STEP4"
        assert workflow["step_authorization"]["baseline_experiment_id"] == "E01"
    finally: service.close()

def test_explore_and_upgrade_keep_beta_max_not_below_beta(tmp_path):
    """beta <= beta_max 是 MATLAB 参数信封的硬校验；任何候选路径都不得违反。"""
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({"name":"BetaEnv","goal":"信封合法","mode":"DEEP_OPTIMIZATION"})
        service.store.create_experiment({**_experiment("STEP3"),"id":"E01","research_id":research["id"],
            "status":"SUCCESS","round_number":3,
            "parameters":{"volfrac":.35,"beta":4.0,"beta_max":2.0,"penal":3.,"rmin":2.,"max_iter":2}})
        service.store.update_experiment("E01", result={"objective":{"compliance":.27},
            "constraints":{"volume_fraction":.35},
            "quality":{"gray_ratio":.6,"connected_components":1},"artifacts":{}})
        for intent, kwargs in (("EXPLORE_PARAMETER", {"factor": "beta"}),
                               ("UPGRADE_FIDELITY", {})):
            proposals = service.tools.policy_compile_intent(
                research["id"], intent=intent, source_experiment="E01",
                _decision_source="RULE_FALLBACK", **kwargs)
            assert proposals, f"{intent} 应有候选"
            for proposal in proposals:
                params = proposal["parameters"]
                assert float(params["beta"]) <= float(params["beta_max"]), (intent, params)
    finally: service.close()

def test_legacy_database_is_backed_up_and_names_are_migrated(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    created = service.create_research({"name":"Legacy","goal":"Migrate","mode":"DEEP_OPTIMIZATION"})
    db_path = service.store.db_path
    service.close()
    with sqlite3.connect(db_path) as db:
        db.execute("UPDATE research SET mode='AUTONOMOUS' WHERE id=?", (created["id"],))
        db.execute("PRAGMA user_version=0")
    reopened = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        assert db_path.with_suffix(db_path.suffix + ".pre-2.1.0.bak").is_file()
        assert reopened.get_research(created["id"])["mode"] == "DEEP_OPTIMIZATION"
        with sqlite3.connect(db_path) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 210
    finally: reopened.close()


def test_autonomous_start_requires_persisted_goal_and_hypothesis(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({
            "name": "Missing hypothesis", "goal": "降低柔度",
            "mode": "DEEP_OPTIMIZATION",
        })
        with pytest.raises(ValueError, match="保存研究目标和研究假设"):
            service.start_autonomous_research(research["id"])
        assert service.store.list_experiments(research["id"]) == []
    finally:
        service.close()


def test_user_selected_usable_candidate_becomes_next_step_baseline(tmp_path, monkeypatch):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(service, "_send_pi_or_fallback", lambda *_args: None)
    try:
        research = service.create_research({
            "name": "Human choice", "goal": "比较候选",
            "hypothesis": "不同受控方向会产生不同结果", "mode": "DEEP_OPTIMIZATION",
        })
        for experiment_id, compliance in (("E01", 1.0), ("E02", 2.0), ("E03", 3.0)):
            service.store.create_experiment({
                **_experiment("STEP1"), "id": experiment_id,
                "research_id": research["id"], "status": "SUCCESS", "round_number": 1,
            })
            service.store.update_experiment(experiment_id, result={
                "objective": {"compliance": compliance},
                "constraints": {"volume_fraction": .4},
                "quality": {"gray_ratio": .02, "connected_components": 1},
                "artifacts": {},
            })
        service.store.append_event(
            research["id"], "HUMAN", "FIDELITY_STAGE_AWAITING_DECISION", "Step1 complete",
            payload={"stage_code": "STEP1", "round": 1,
                     "experiment_ids": ["E01", "E02", "E03"],
                     "best_experiment_id": "E01", "result": {"successful": 3, "failed": 0}},
        )
        decided = service.decide_fidelity_stage(
            research["id"], "ADVANCE_STAGE", selected_experiment_id="E02")
        authorization = decided["defaults"]["autonomous_workflow"]["step_authorization"]
        assert authorization["baseline_experiment_id"] == "E02"
    finally:
        service.close()


def test_failed_partial_result_is_evidence_but_not_a_usable_baseline():
    assert not ResearchService._has_usable_stage_result({
        "status": "FAILED",
        "result": {"objective": {"compliance": 12.5}},
    })


def test_user_can_finish_before_step4_and_preview_truthful_report(tmp_path):
    service = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    try:
        research = service.create_research({
            "name": "Early finish", "goal": "检查流程",
            "hypothesis": "当前证据可能不足", "mode": "DEEP_OPTIMIZATION",
        })
        finished = service.finish_research(research["id"])
        assert finished["status"] == "STOPPED"
        assert finished["termination_reason"] == "USER_FINISHED"
        preview = service.report_preview(research["id"])
        assert "用户决定提前结束研究" in preview["markdown"]
        assert "不得据此宣称研究成功" in preview["markdown"]
    finally:
        service.close()
