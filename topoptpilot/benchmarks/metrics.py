"""Fixed-budget solver and agent-quality metrics from authoritative records."""

from __future__ import annotations

import math

from topoptpilot.fidelity import FidelityManager


def _finite_compliance(experiment: dict) -> float | None:
    value = (experiment.get("result") or {}).get("objective", {}).get("compliance")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def campaign_metrics(experiments: list[dict], events: list[dict] | None = None,
                     decisions: list[dict] | None = None, reference_best: float | None = None) -> dict:
    events, decisions = events or [], decisions or []
    completed = [item for item in experiments if item.get("result")]
    feasible = [item for item in completed if item["status"] == "SUCCESS"]
    rank = {"F0": 0, "F1": 1, "F2": 2, "F3": 3}
    highest = max((rank.get(str(item.get("fidelity", "F0")).split()[0], 0)
                   for item in feasible), default=0)
    comparable = [item for item in feasible
                  if rank.get(str(item.get("fidelity", "F0")).split()[0], 0) == highest]
    comparable_values = [value for item in comparable
                         if (value := _finite_compliance(item)) is not None]
    raw_values = [value for item in completed
                  if (value := _finite_compliance(item)) is not None]
    best = min(comparable_values, default=None)
    best_raw = min(raw_values, default=None)
    best_gray_raw = min((item["result"]["quality"].get("gray_ratio", 1)
                         for item in completed), default=None)
    first_feasible = next((index for index, item in enumerate(completed, 1)
                           if item["status"] == "SUCCESS"), None)
    high_fidelity = sum(str(item.get("fidelity", "F0")).startswith(("F2", "F3"))
                        for item in completed)
    costs = sum(FidelityManager.estimated_cost(str(item.get("fidelity", "F0")).split()[0])
                for item in completed)
    signatures, repeats = set(), 0
    for item in experiments:
        signature = (str(item.get("fidelity", "F0")).split()[0],
                     tuple(sorted((key, repr(value)) for key, value in item["parameters"].items())))
        repeats += signature in signatures
        signatures.add(signature)
    tool_calls = [item for item in events if item.get("kind") == "TOOL_CALL"]
    compile_calls = [item for item in tool_calls if item.get("title") == "policy_compile_intent"]
    rejected = [item for item in events if item.get("kind") == "SAFETY POLICY"
                and "REJECTED" in item.get("title", "")]
    invalid = [item for item in events if item.get("title") == "INVALID INTENT"]
    upgrades_without_success = sum(
        str(item.get("fidelity", "F0")).startswith(("F2", "F3"))
        and not any(previous["status"] == "SUCCESS" for previous in completed[:index])
        for index, item in enumerate(completed)
    )
    return {
        "best_feasible_objective": best,
        "experiments_to_feasible": first_feasible,
        "high_fidelity_runs": high_fidelity,
        "constraint_violation_rate": (None if not completed else
                                      sum(item["status"] != "SUCCESS" for item in completed) / len(completed)),
        # Secondary metrics stay informative even if a short fixed budget never
        # reaches the complete feasibility definition. The primary metric above
        # remains strictly feasibility-gated.
        "best_compliance": best_raw,
        "best_gray_ratio": best_gray_raw,
        "total_fem_cost": costs,
        "human_interventions": len([item for item in events if item.get("kind") == "HUMAN OVERRIDE"]),
        "final_regret": (None if best is None or reference_best is None else best - reference_best),
        "invalid_intent_rate": (0.0 if not compile_calls else len(invalid) / len(compile_calls)),
        "policy_rejection_rate": (0.0 if not compile_calls else len(rejected) / len(compile_calls)),
        "repeated_experiment_rate": (0.0 if not experiments else repeats / len(experiments)),
        "unnecessary_fidelity_upgrade_rate": (0.0 if high_fidelity == 0 else
                                               upgrades_without_success / high_fidelity),
        "approval_count": len([item for item in decisions if item.get("status") == "APPROVED"]),
    }
