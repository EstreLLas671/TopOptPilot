"""Pure research decisions; persistence and transport stay in ResearchService."""

from __future__ import annotations

from typing import Any

from topoptpilot.agent import build_analysis, build_feedback, build_initial_plan
from topoptpilot.evaluator import evaluate_result
from topoptpilot.evaluator.failure_detector import detect_failure
from topoptpilot.policy import evaluate_safety
from topoptpilot.policy.action_policy import choose_action


class ResearchOrchestrator:
    def initial_plan(self, research: dict[str, Any]) -> str:
        return build_initial_plan(research["budget_total"])

    def inspect_proposal(self, experiment: dict[str, Any]) -> dict[str, Any]:
        return evaluate_safety(experiment["parameters"], experiment["fidelity"])

    def analyze(self, research: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        evaluation = evaluate_result(result, research["constraints"])
        evaluation["next_action"] = choose_action(evaluation)
        evaluation["failure"] = detect_failure(result, research["constraints"])
        return {
            "evaluation": evaluation,
            "analysis": build_analysis(result, evaluation),
            "feedback": build_feedback(evaluation),
        }
