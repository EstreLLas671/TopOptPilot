from __future__ import annotations

import time

import pytest

from topoptpilot_desktop.demo_router import (
    DEMO_RESEARCH_ID,
    DEMO_RUN_ID,
    demo_autonomous,
    demo_candidate_confirm,
    demo_engineering_file,
    demo_engineering_run,
    demo_finish,
    demo_research_from_engineering,
    demo_stage_decision,
    four_round_demo_manifest,
    state,
)


def _complete_active_stage() -> dict:
    state.stage_started = time.monotonic() - 20
    return state.research()


def test_manifest_uses_documented_real_results() -> None:
    payload = four_round_demo_manifest()

    assert payload["versionLabel"].endswith("演示版")
    assert [item["runName"] for item in payload["rounds"]] == ["round1", "round2", "round3", "round4_final"]
    assert payload["rounds"][0]["compliance"] == pytest.approx(0.09822546369868759)
    assert payload["rounds"][1]["compliance"] == payload["rounds"][0]["compliance"]
    assert payload["rounds"][2]["grayRatio"] == pytest.approx(0.0032552083333333335)
    assert payload["rounds"][3]["grayRatio"] == pytest.approx(0.0006510416666666666)
    assert payload["rounds"][3]["converged"] is True
    assert [item["source"] for item in payload["candidates"]] == [
        "experiments_rerun/s3_base/step3_result.json",
        "experiments_rerun/s3_cont_b2m16/step3_result.json",
        "experiments_rerun/s3_move005/step3_result.json",
    ]
    assert payload["allPassed"] is True


def test_complete_desktop_flow_keeps_three_candidates_only_in_step1() -> None:
    run = demo_engineering_run()
    assert run["runId"] == DEMO_RUN_ID
    state.engineering_started = time.monotonic() - 20
    research = demo_research_from_engineering(DEMO_RUN_ID)
    assert research["experiments"] == []

    demo_autonomous(DEMO_RESEARCH_ID)
    research = demo_candidate_confirm(DEMO_RESEARCH_ID)
    assert len([item for item in research["experiments"] if item["fidelity"] == "STEP1"]) == 3
    research = _complete_active_stage()
    assert all(item["status"] == "SUCCESS" for item in research["experiments"])

    for stage in (2, 3, 4):
        research = demo_stage_decision(DEMO_RESEARCH_ID, {"action": "ADVANCE_STAGE", "selectedExperimentId": research["best_experiment"]["id"]})
        assert len([item for item in research["experiments"] if item["fidelity"] == f"STEP{stage}"]) == 1
        research = _complete_active_stage()

    completed = demo_finish(DEMO_RESEARCH_ID)
    assert completed["status"] == "COMPLETED"
    assert completed["best_experiment"]["id"] == "DEMO-E-STEP4"


def test_engineering_artifacts_are_allowlisted() -> None:
    state.engineering_started = time.monotonic() - 20
    response = demo_engineering_file(DEMO_RUN_ID, "result_manifest.json")
    assert response.media_type == "application/json"

    with pytest.raises(Exception) as exc_info:
        demo_engineering_file(DEMO_RUN_ID, "../../AGENTS.md")
    assert getattr(exc_info.value, "status_code", None) == 400
