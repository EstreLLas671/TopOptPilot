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
from topoptpilot.nomenclature import normalize_mode, normalize_stage, stage_label


FIDELITY_LABELS = {
    item: stage_label(item.value) for item in Fidelity
}


DEEP_OPTIMIZATION_MUTABLE_PARAMETERS = {"volfrac", "beta", "beta_max", "projection", "controller", "move"}

class IntentCompiler:
    def __init__(self, fidelity_manager: FidelityManager | None = None):
        self.fidelity_manager = fidelity_manager or FidelityManager()

    def compile(self, research: dict[str, Any], experiments: list[dict[str, Any]],
                request: IntentRequest | dict[str, Any]) -> list[ExperimentProposal]:
        intent = request if isinstance(request, IntentRequest) else IntentRequest.model_validate(request)
        source = self._source(experiments, intent.source_experiment)
        base = self._base_parameters(research, source)
        current_fidelity = self._fidelity(source)
        workflow = (research.get("defaults") or {}).get("autonomous_workflow") or {}
        active_stage = str(workflow.get("active_fidelity") or "")
        forced_fidelity = Fidelity(normalize_stage(active_stage)) if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION" and active_stage else None
        candidates: list[tuple[str, Fidelity, dict[str, Any], list[str]]] = []

        if intent.intent == IntentType.ESTABLISH_BASELINE:
            params = {**base, "beta": 1.0}
            candidates.append(("Establish a reproducible Step1 baseline", Fidelity.STEP1, params,
                               ["baseline"]))
        elif intent.intent == IntentType.EXPLORE_PARAMETER:
            factor = intent.factor or "beta"
            levels = self._levels(factor, base)
            for value in levels:
                params = {**base, factor: value}
                candidates.append((f"Explore {factor}={value}", Fidelity.STEP1, params, [factor]))
        elif intent.intent == IntentType.REDUCE_GRAYNESS:
            current_beta = float(base.get("beta", 1.0))
            # Pick the smallest novel beta above the current value so the
            # REDUCE proposal is not collapsed by dedup against EXPLORE siblings.
            existing_betas = {
                float((item.get("parameters") or {}).get("beta", 0))
                for item in experiments
                if str(item.get("fidelity", "")).split()[0] == current_fidelity.value
            }
            new_beta = min(32.0, max(current_beta + 1.0, current_beta * 3))
            while new_beta in existing_betas and new_beta < 32.0:
                new_beta = min(32.0, new_beta * 1.5)
            new_beta = min(32.0, max(2.0, new_beta))
            params = {**base, "beta": new_beta}
            # beta_max 是投影强度的上限界：求解器要求 beta <= beta_max，
            # 续升 beta 时随行抬升，否则 MATLAB 参数信封会拒绝整个任务。
            params["beta_max"] = min(
                64.0, max(64.0, new_beta, float(base.get("beta_max", 0) or 0))
            )
            candidates.append(("Reduce grayness with one bounded projection step",
                               current_fidelity, params, ["beta"]))
        elif intent.intent == IntentType.RESTORE_CONNECTIVITY:
            beta_params = {**base, "beta": max(1.0, float(base.get("beta", 8)) / 2)}
            move_params = {**base, "move": max(.05, float(base.get("move", .2)) / 2)}
            candidates.append(("Test whether gentler projection restores connectivity",
                               current_fidelity, beta_params, ["beta"]))
            candidates.append(("Test whether a smaller OC move restores connectivity",
                               current_fidelity, move_params, ["move"]))
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
        existing = {(normalize_stage(item.get("fidelity")),
                     self.canonical_parameter_key(item.get("parameters", {}))) for item in experiments}
        for purpose, fidelity, parameters, factors in candidates:
            if forced_fidelity is not None: fidelity = forced_fidelity
            parameters.update(research.get("locks", {}))
            # beta_max 是投影强度的上限界（beta <= beta_max 是 MATLAB 参数信封的
            # 硬性校验）；任何路径产生的候选都必须维持该不变量，否则 Step4
            # 会继承到非法组合而被信封秒拒。
            beta_value = float(parameters.get("beta", 1.0) or 1.0)
            beta_max_value = float(parameters.get("beta_max", beta_value) or beta_value)
            if beta_max_value < beta_value:
                parameters["beta_max"] = beta_value
            if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION":
                # ``baseline`` and ``fidelity`` are provenance labels, not
                # solver parameters proposed for mutation.
                controlled = [factor for factor in factors
                              if factor not in {"baseline", "fidelity"}]
                if len(controlled) > 1 or any(factor not in DEEP_OPTIMIZATION_MUTABLE_PARAMETERS for factor in controlled): continue
            if (fidelity.value, self.canonical_parameter_key(parameters)) in existing:
                # 升级/验证类意图是对既定方案的重新求解，属于"重复本阶段"的
                # 正当操作；被查重吞掉会让 Step3→Step4 的验证轮永远无法开跑。
                if intent.intent not in {IntentType.UPGRADE_FIDELITY, IntentType.VERIFY_CANDIDATE}:
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

    # The solver task builder fills these defaults before an experiment is
    # stored, so history checks must compare the same canonical shape;
    # otherwise sparse compile-time dicts never match normalized stored dicts
    # and an already-run configuration can be proposed twice.
    _CANONICAL_KEYS = ("volfrac", "beta", "beta_max", "projection", "controller", "move",
                       "penal", "rmin", "max_iter", "min_iter", "filter_strategy")

    @classmethod
    def canonical_parameter_key(cls, parameters: dict[str, Any]) -> tuple:
        params = {key: parameters.get(key) for key in cls._CANONICAL_KEYS}
        beta = params.get("beta")
        if beta is None:
            beta = params.get("beta_max")
        beta = 1.0 if beta is None else float(beta)
        params["beta"] = beta
        beta_max = params.get("beta_max")
        params["beta_max"] = float(beta_max if beta_max is not None else max(beta, 32.0 if beta > 1 else 2.0))
        if params.get("projection") is None:
            params["projection"] = "heaviside_projection" if beta > 1 else "none"
        if params.get("controller") is None:
            params["controller"] = ("periodic_controller" if params["projection"] != "none"
                                    else "fixed_controller")
        if params.get("move") is None:
            params["move"] = 0.2
        for key, default in (("volfrac", 0.4), ("penal", 3.0), ("rmin", 1.5),
                             ("max_iter", 80), ("min_iter", 10), ("filter_strategy", "fixed")):
            if params.get(key) is None:
                params[key] = default
        normalized: list[tuple[str, Any]] = []
        for key in cls._CANONICAL_KEYS:
            value = params[key]
            if isinstance(value, float):
                value = round(value, 9)
            elif isinstance(value, (int,)) and not isinstance(value, bool):
                value = round(float(value), 9)
            normalized.append((key, value))
        return tuple(normalized)

    @staticmethod
    def _parameter_key(parameters: dict[str, Any]) -> tuple:
        return IntentCompiler.canonical_parameter_key(parameters)

    @staticmethod
    def _source(experiments: list[dict[str, Any]], requested: str | None) -> dict | None:
        if requested:
            return next((item for item in experiments if item["id"] == requested), None)
        completed = [item for item in experiments
                     if item.get("result") and not item["result"].get("partial")]
        return completed[-1] if completed else (experiments[-1] if experiments else None)

    @staticmethod
    def _base_parameters(research: dict[str, Any], source: dict | None) -> dict[str, Any]:
        configured = ((research.get("defaults") or {}).get("optimization_config") or {})
        fixed = {"penal": float(configured.get("penal", 3.0)), "rmin": float(configured.get("rmin", 1.5)), "max_iter": int(configured.get("maxIterations", 80)), "min_iter": int(configured.get("minIterations", 10)), "filter_strategy": str(configured.get("filterStrategy", "fixed"))}
        if source:
            previous = dict(source["parameters"])
            mutable = {key: value for key, value in previous.items() if key in DEEP_OPTIMIZATION_MUTABLE_PARAMETERS}
            return {**fixed, **mutable}
        constraints = research.get("constraints", {})
        return {**fixed, "volfrac": float(configured.get("volfrac", constraints.get("volume_fraction", 0.4))), "beta": 1.0}

    @staticmethod
    def _fidelity(source: dict | None) -> Fidelity:
        if not source:
            return Fidelity.STEP1
        return Fidelity(normalize_stage(source.get("fidelity")))

    @staticmethod
    def _levels(factor: str, base: dict[str, Any]) -> list[float]:
        if factor == "beta":
            return [2.0, 4.0, 8.0]
        if factor == "move":
            current = float(base.get("move", 0.2))
            return sorted({max(0.05, current / 2), current, min(0.4, current * 1.5)})
        if factor == "volfrac":
            current = float(base.get("volfrac", 0.4))
            return sorted({max(0.1, current - 0.05), current, min(0.7, current + 0.05)})
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
