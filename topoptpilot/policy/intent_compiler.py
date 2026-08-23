"""Deterministic scientific-intent compiler.

The agent decides what question to answer. This module decides which bounded,
controlled FEM configurations are legal ways to answer it.
"""

from __future__ import annotations

import uuid
from typing import Any

from topoptpilot.fidelity import FidelityManager
from topoptpilot.policy.doe_templates import discriminating_experiments
from topoptpilot.policy.safety_guard import evaluate_safety
from topoptpilot.schemas import ExperimentProposal, Fidelity, IntentRequest, IntentType, SafetyStatus


FIDELITY_LABELS = {
    Fidelity.F0: "F0 — MATLAB 2D Coarse", Fidelity.F1: "F1 — MATLAB 2D Fine",
    Fidelity.F2: "F2 — MATLAB 3D Coarse", Fidelity.F3: "F3 — MATLAB 3D Fine",
}


class IntentCompiler:
    def __init__(self, fidelity_manager: FidelityManager | None = None):
        self.fidelity_manager = fidelity_manager or FidelityManager()

    def compile(self, research: dict[str, Any], experiments: list[dict[str, Any]],
                request: IntentRequest | dict[str, Any]) -> list[ExperimentProposal]:
        intent = request if isinstance(request, IntentRequest) else IntentRequest.model_validate(request)
        source = self._source(experiments, intent.source_experiment)
        base = self._base_parameters(research, source)
        current_fidelity = self._fidelity(source)
        candidates: list[tuple[str, Fidelity, dict[str, Any], list[str]]] = []

        if intent.intent == IntentType.ESTABLISH_BASELINE:
            params = {**base, "beta": 1.0, "rmin": 1.5, "penal": 3.0}
            candidates.append(("Establish a reproducible F0 baseline", Fidelity.F0, params,
                               ["baseline"]))
        elif intent.intent == IntentType.EXPLORE_PARAMETER:
            factor = intent.factor or "beta"
            levels = self._levels(factor, base)
            for value in levels:
                params = {**base, factor: value}
                candidates.append((f"Explore {factor}={value}", Fidelity.F0, params, [factor]))
        elif intent.intent == IntentType.REDUCE_GRAYNESS:
            params = {**base, "beta": min(32.0, max(2.0, float(base.get("beta", 1)) * 2))}
            candidates.append(("Reduce grayness with one bounded projection step",
                               current_fidelity, params, ["beta"]))
        elif intent.intent == IntentType.RESTORE_CONNECTIVITY:
            beta_params = {**base, "beta": max(1.0, float(base.get("beta", 8)) / 2)}
            radius_params = {**base, "rmin": min(4.0, float(base.get("rmin", 1.5)) + .5)}
            candidates.append(("Test whether gentler projection restores connectivity",
                               current_fidelity, beta_params, ["beta"]))
            candidates.append(("Test whether a wider filter restores connectivity",
                               current_fidelity, radius_params, ["rmin"]))
        elif intent.intent == IntentType.TEST_COMPETING_EXPLANATIONS:
            template = self._template(intent)
            for item in discriminating_experiments(template, base):
                candidates.append((item["purpose"], current_fidelity, item["parameters"],
                                   item["controlled_factors"]))
        elif intent.intent in {IntentType.UPGRADE_FIDELITY, IntentType.VERIFY_CANDIDATE}:
            target = Fidelity(self.fidelity_manager.promote_code(current_fidelity.value))
            candidates.append((f"Verify transfer at {FIDELITY_LABELS[target]}", target, base,
                               ["fidelity"]))

        proposals = []
        existing = {(str(item.get("fidelity", "F0")).split()[0],
                     self._parameter_key(item.get("parameters", {}))) for item in experiments}
        for purpose, fidelity, parameters, factors in candidates:
            parameters.update(research.get("locks", {}))
            if (fidelity.value, self._parameter_key(parameters)) in existing:
                continue
            safety = evaluate_safety(parameters, FIDELITY_LABELS[fidelity])
            status = (SafetyStatus.PASS if safety["safe"] and not safety["requires_approval"]
                      else SafetyStatus.PENDING_HUMAN_APPROVAL if safety["safe"]
                      else SafetyStatus.REJECTED)
            proposals.append(ExperimentProposal(
                id=f"P-{uuid.uuid4().hex[:10].upper()}", research_id=research["id"],
                intent=intent.intent, purpose=purpose, fidelity=fidelity,
                backend=self.fidelity_manager.backend_for(fidelity.value), parameters=parameters,
                estimated_cost=self.fidelity_manager.estimated_cost(fidelity.value),
                risk=str(safety["risk"]), safety_status=status,
                approval_required=bool(safety["requires_approval"]),
                source_experiment=source.get("id") if source else None,
                controlled_factors=factors,
            ))
        return proposals

    @staticmethod
    def _parameter_key(parameters: dict[str, Any]) -> tuple:
        return tuple(sorted((key, repr(value)) for key, value in parameters.items()
                            if key != "initial_density"))

    @staticmethod
    def _source(experiments: list[dict[str, Any]], requested: str | None) -> dict | None:
        if requested:
            return next((item for item in experiments if item["id"] == requested), None)
        completed = [item for item in experiments if item.get("result")]
        return completed[-1] if completed else (experiments[-1] if experiments else None)

    @staticmethod
    def _base_parameters(research: dict[str, Any], source: dict | None) -> dict[str, Any]:
        if source:
            return dict(source["parameters"])
        constraints = research.get("constraints", {})
        return {"volfrac": float(constraints.get("volume_fraction", 0.4)), "rmin": 1.5,
                "penal": 3.0, "beta": 1.0, "max_iter": 80}

    @staticmethod
    def _fidelity(source: dict | None) -> Fidelity:
        if not source:
            return Fidelity.F0
        prefix = str(source.get("fidelity", "F0")).split()[0]
        return Fidelity(prefix) if prefix in {item.value for item in Fidelity} else Fidelity.F0

    @staticmethod
    def _levels(factor: str, base: dict[str, Any]) -> list[float]:
        if factor == "beta":
            return [2.0, 4.0, 8.0]
        if factor == "rmin":
            return [1.25, 1.75, 2.25]
        if factor == "penal":
            return [2.0, 3.0, 4.0]
        raise ValueError(f"Unsupported exploration factor: {factor}")

    @staticmethod
    def _template(intent: IntentRequest) -> str:
        factors = set(intent.factors)
        if factors == {"beta", "rmin"} or not factors:
            return "beta_vs_rmin"
        if factors == {"beta", "penal"}:
            return "beta_vs_penal"
        if factors == {"projection", "controller"}:
            return "projection_vs_controller"
        raise ValueError("No controlled DOE template exists for the requested factors")
