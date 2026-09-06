"""Build the L0-L3 research-memory hierarchy from authoritative state."""

from __future__ import annotations

from typing import Any

from topoptpilot.nomenclature import normalize_stage


class ResearchMemory:
    def build(self, research: dict[str, Any], experiments: list[dict[str, Any]],
              events: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> dict[str, Any]:
        l0 = [{"experiment_id": item["id"], "artifacts": self._artifact_refs(item)}
              for item in experiments if item.get("result")]
        l1 = [self._experiment_record(item) for item in experiments]
        l2 = self._scientific_memory(l1, research.get("constraints", {}))
        defaults = research.get("defaults") or {}
        workflow = defaults.get("autonomous_workflow") or {}
        authoritative_config = defaults.get("optimization_config") or {}
        l3 = {
            "research_id": research["id"], "goal": research["goal"],
            "constraints": research["constraints"], "hypothesis": research.get("hypothesis"),
            "best_candidate": l2["best_candidate"], "recent_experiments": l1[-6:],
            "parameter_trends": l2["parameter_trends"], "known_failures": l2["known_failures"],
            "pareto_candidates": l2["pareto_candidates"],
            "current_question": research.get("current_question"),
            "current_round": research.get("current_round", 0),
            "active_fidelity": normalize_stage(workflow.get("active_fidelity")),
            "authoritative_optimization_config": authoritative_config,
            "deep_optimization_mutable_parameters": [
                "volfrac", "beta", "beta_max", "projection", "controller", "move",
            ],
            "immutable_visible_parameters": [
                "dimension", "bcType", "accuracy", "dimensions", "unit",
                "cellSizeMeters", "nelx", "nely", "nelz", "penal", "rmin",
                "minIterations", "maxIterations", "filterStrategy", "material",
            ],
            "geometry": research.get("geometry") or {},
            "material": research.get("material") or {},
            "loads": research.get("loads") or [],
            "boundary_conditions": research.get("boundary_conditions") or {},
            "locks": research.get("locks") or {},
            "pending_decisions": [item for item in decisions if item["status"] == "PENDING"],
            "recent_evidence": [self._compact_event(item) for item in events[-8:]
                                if item["kind"] in {"EVIDENCE", "ANALYSIS", "NEXT DECISION"}],
        }
        return {"L0": l0, "L1": l1, "L2": l2, "L3": l3}

    @staticmethod
    def _artifact_refs(experiment: dict) -> dict:
        artifacts = (experiment.get("result") or {}).get("artifacts", {})
        return {key: value for key, value in artifacts.items()
                if key in {"density_path", "history_path", "solver_output_path", "log", "vtk", "stl"}}

    @staticmethod
    def _experiment_record(item: dict) -> dict:
        result = item.get("result") or {}
        return {
            "id": item["id"], "status": item["status"], "fidelity": item["fidelity"],
            "purpose": item["purpose"], "intent": item.get("intent", "MANUAL"),
            "parameters": item["parameters"], "objective": result.get("objective", {}),
            "constraints": result.get("constraints", {}), "quality": result.get("quality", {}),
            "failure": (result.get("evaluation") or {}).get("failure"),
            "cached": bool(item.get("cached")),
        }

    @classmethod
    def _scientific_memory(cls, records: list[dict], constraints: dict | None = None) -> dict:
        constraints = constraints or {}
        completed = [item for item in records if item["objective"].get("compliance") is not None]
        feasible = [item for item in completed if item["status"] == "SUCCESS"]
        rank = {"STEP1": 0, "STEP2": 1, "STEP3": 2, "STEP4": 3}
        highest = max((rank.get(str(item["fidelity"]).split()[0], 0) for item in feasible), default=0)
        comparable = [item for item in feasible
                      if rank.get(str(item["fidelity"]).split()[0], 0) == highest]
        best = min(comparable, key=lambda item: item["objective"]["compliance"], default=None)
        failures = []
        for item in completed:
            quality = item["quality"]
            if quality.get("connected_components", 1) != 1:
                failures.append({"type": "DISCONNECTION", "experiment_id": item["id"],
                                 "evidence": {"components": quality.get("connected_components")}})
            if quality.get("gray_ratio", 0) > float(constraints.get("gray_max", 0.05)):
                failures.append({"type": "HIGH_GRAY", "experiment_id": item["id"],
                                 "evidence": {"gray_ratio": quality.get("gray_ratio")}})
        return {
            "best_candidate": best,
            "known_failures": failures[-12:],
            "parameter_trends": cls._trends(completed),
            "pareto_candidates": cls.pareto(completed),
        }

    @staticmethod
    def _trends(records: list[dict]) -> dict:
        trends: dict[str, list[dict]] = {"beta": [], "rmin": [], "penal": []}
        for item in records:
            for factor in trends:
                if factor in item["parameters"]:
                    trends[factor].append({
                        "experiment_id": item["id"], "value": item["parameters"][factor],
                        "compliance": item["objective"].get("compliance"),
                        "gray_ratio": item["quality"].get("gray_ratio"),
                        "components": item["quality"].get("connected_components"),
                    })
        return trends

    @staticmethod
    def pareto(records: list[dict]) -> list[dict]:
        points = [item for item in records
                  if item["objective"].get("compliance") is not None
                  and item["quality"].get("gray_ratio") is not None
                  and item["quality"].get("connected_components", 1) == 1]
        result = []
        for candidate in points:
            c = candidate["objective"]["compliance"]
            g = candidate["quality"]["gray_ratio"]
            dominated = any(
                other is not candidate
                and other["fidelity"] == candidate["fidelity"]
                and other["objective"]["compliance"] <= c
                and other["quality"]["gray_ratio"] <= g
                and (other["objective"]["compliance"] < c or other["quality"]["gray_ratio"] < g)
                for other in points
            )
            if not dominated:
                result.append({"experiment_id": candidate["id"], "compliance": c,
                               "gray_ratio": g, "fidelity": candidate["fidelity"]})
        return sorted(result, key=lambda item: item["compliance"])

    @staticmethod
    def _compact_event(event: dict) -> dict:
        return {"id": event["id"], "kind": event["kind"], "title": event["title"],
                "experiment_id": event.get("experiment_id"), "payload": event.get("payload", {})}
