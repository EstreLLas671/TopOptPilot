"""Executable regression workflows for the three formal V5 cases.

These workflows exercise the same intent compiler, approval path, asynchronous
queue and evaluator as the Workspace. They never inject second-round numbers.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from topoptpilot.benchmarks.metrics import campaign_metrics


class EvidenceCaseRunner:
    def __init__(self, service, timeout: float = 180):
        self.service, self.timeout = service, timeout
        self.root = Path(__file__).resolve().parent

    @staticmethod
    def _met_targets(item: dict) -> bool:
        """契约阈值是审查条件：达标与否看评估器结论，旧记录回退到状态。"""
        evaluation = (item.get("result") or {}).get("evaluation") or {}
        if "feasible" in evaluation:
            return bool(evaluation["feasible"])
        return item.get("status") == "SUCCESS"

    def run(self, case_id: str) -> dict:
        case_id = case_id.upper()
        definition = self._definition(case_id)
        research = self.service.create_research({
            "name": definition["name"], "goal": definition["goal"], "mode": "CONTROLLED",
            "geometry": definition["geometry"], "constraints": definition["constraints"],
            "material": definition.get("material", {}), "loads": definition.get("loads", []),
            "boundary_conditions": definition.get("boundary_conditions", {}),
            "hypothesis": definition["hypothesis"], "budget_total": 12,
            "budgets": {"total": 12, "f0": 8, "f1": 2, "f2": 1, "f3": 1},
        })
        rid = research["id"]
        if case_id == "A": self._case_a(rid)
        elif case_id == "B": self._case_b(rid)
        elif case_id == "C": self._case_c(rid)
        else: raise ValueError(f"Unknown case {case_id}")
        state = self.service.get_research(rid)
        return {"case": case_id, "research_id": rid, "definition": definition,
                "experiments": state["experiments"],
                "metrics": campaign_metrics(state["experiments"], state["events"], state["decisions"])}

    def _case_a(self, rid: str) -> None:
        baseline = self._intent(rid, "ESTABLISH_BASELINE")[0]
        explored = self._intent(rid, "EXPLORE_PARAMETER", factor="beta",
                                source_experiment=baseline["id"])
        # Pick the experiment closest to feasibility (lowest gray ratio among
        # those that are still above the limit) as the REDUCE continuation seed.
        best = min(explored, key=lambda item: item["result"]["quality"].get("gray_ratio", 1.0))
        # Projection continuation: keep sharpening beta until the Evaluator marks
        # the design feasible or the F0 budget is exhausted. This is the "AI
        # improves effectiveness across rounds" loop the cases demonstrate.
        budget_after_explore = 8 - 1 - len(explored)
        best_gray = float(best["result"]["quality"].get("gray_ratio", 1.0))
        for _ in range(budget_after_explore):
            if self._met_targets(best):
                break
            refined = self._intent(rid, "REDUCE_GRAYNESS", source_experiment=best["id"])
            if not refined: break
            candidate = refined[0]
            new_gray = float(candidate["result"]["quality"].get("gray_ratio", 1.0))
            new_conn = int(candidate["result"]["quality"].get("connected_components", 1))
            if new_gray >= 0.95 or new_conn == 0:
                break
            best_gray = new_gray
            best = candidate

    def _case_b(self, rid: str) -> None:
        current = self._intent(rid, "ESTABLISH_BASELINE")[0]
        generated = [current]
        best_gray = float(current["result"]["quality"].get("gray_ratio", 1.0))
        for _ in range(4):
            values = self._intent(rid, "REDUCE_GRAYNESS", source_experiment=current["id"])
            if not values: break
            new_exp = values[0]
            new_gray = float(new_exp["result"]["quality"].get("gray_ratio", 1.0))
            new_conn = int(new_exp["result"]["quality"].get("connected_components", 1))
            # Stop only on total collapse (all-gray or disconnected)
            if new_gray >= 0.95 or new_conn == 0:
                generated.append(new_exp)
                break
            if new_gray < best_gray:
                best_gray = new_gray
            current = new_exp
            generated.append(new_exp)
        # Use the best (lowest gray) experiment overall as the study target —
        # even if it is connected, it still exceeds the gray limit and the
        # competing-explanations DOE reveals which parameters to adjust next.
        failure = min(generated, key=lambda item: item["result"]["quality"].get("gray_ratio", 1))
        self._intent(rid, "TEST_COMPETING_EXPLANATIONS", source_experiment=failure["id"],
                     explanations=["beta too high", "rmin too low"], factors=["beta", "rmin"])

    def _case_c(self, rid: str) -> None:
        baseline = self._intent(rid, "ESTABLISH_BASELINE")[0]
        explored = self._intent(rid, "EXPLORE_PARAMETER", factor="beta",
                                source_experiment=baseline["id"])
        feasible = [item for item in explored if self._met_targets(item)]
        current = (min(feasible, key=lambda item: item["result"]["objective"]["compliance"])
                   if feasible else min(explored, key=lambda item: (
                       item["result"]["quality"].get("connected_components", 1) != 1,
                       item["result"]["quality"].get("gray_ratio", 1))))
        budget_after_explore = 8 - 1 - len(explored)
        for _ in range(budget_after_explore):
            if self._met_targets(current): break
            refined = self._intent(rid, "REDUCE_GRAYNESS", source_experiment=current["id"])
            if not refined: break
            current = refined[0]
        for _ in range(3):
            values = self._intent(rid, "UPGRADE_FIDELITY", source_experiment=current["id"],
                                  approve=True)
            if not values: break
            current = values[0]

    def _intent(self, rid: str, intent: str, approve: bool = False, **arguments) -> list[dict]:
        proposals = self.service.tools.policy_compile_intent(rid, intent=intent, **arguments)
        experiment_ids = []
        for proposal in proposals:
            preview = self.service.tools.experiment_preview(rid, proposal["id"])
            if not preview["can_submit"]: continue
            submitted = self.service.tools.experiment_submit(rid, proposal["id"])["experiment"]
            experiment_ids.append(submitted["id"])
        if approve:
            for decision in self.service.store.list_decisions(rid):
                if decision["status"] == "PENDING" and decision.get("experiment_id") in experiment_ids:
                    self.service.approve_decision(decision["id"])
        return self._wait(experiment_ids)

    def _wait(self, experiment_ids: list[str]) -> list[dict]:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            values = [self.service.get_experiment(item) for item in experiment_ids]
            if all(item["status"] in {"SUCCESS", "FAILED", "CANCELLED"} for item in values):
                return values
            time.sleep(.1)
        raise TimeoutError(f"Experiments did not finish: {experiment_ids}")

    def _definition(self, case_id: str) -> dict:
        matches = sorted(self.root.glob(f"case_{case_id.lower()}_*.json"))
        if not matches: raise KeyError(case_id)
        return json.loads(matches[0].read_text(encoding="utf-8"))
