from __future__ import annotations

from typing import Any
import math


def evaluate_result(result: dict[str, Any], constraints: dict[str, Any]) -> dict[str, Any]:
    quality = result.get("quality", {})
    objective = result.get("objective", {})
    gray = float(quality.get("gray_ratio", 1.0))
    components = int(quality.get("connected_components", 0))
    gray_limit = float(constraints.get("gray_max", 0.05))
    needs_connected = bool(constraints.get("connected", True))
    compliance = objective.get("compliance")
    target_volume = constraints.get("volume_fraction")
    actual_volume = result.get("constraints", {}).get("volume_fraction")
    maximum_stress = quality.get("maximum_von_mises")
    stress_unit_trusted = bool(quality.get("stress_unit_trusted"))
    allowable_stress = next((constraints.get(key) for key in
                             ("allowable_stress_mpa", "stress_limit_mpa", "max_stress_mpa")
                             if constraints.get(key) is not None), None)
    stress_ok = True
    if allowable_stress is not None:
        stress_ok = (stress_unit_trusted and maximum_stress is not None
                     and math.isfinite(float(maximum_stress))
                     and float(maximum_stress) <= float(allowable_stress))
    volume_error = (None if target_volume is None or actual_volume is None else
                    float(actual_volume) - float(target_volume))
    # 求解有效性（决定实验成败）：结果真实、数值完备、求解器正常收敛。
    solver_valid = (compliance is not None and math.isfinite(float(compliance))
                    and (volume_error is None
                         or abs(volume_error) <= float(constraints.get("volume_tolerance", .02)))
                    and result.get("status") not in {"failed", "timeout"})
    # 契约阈值（灰度、连通、应力）是审查条件与优化方向，不决定实验成败。
    checks = {
        "gray": gray <= gray_limit,
        "connected": (components == 1) if needs_connected else True,
        "finite_compliance": compliance is not None and math.isfinite(float(compliance)),
        "volume": volume_error is None or abs(volume_error) <= float(constraints.get("volume_tolerance", .02)),
        "stress": stress_ok,
    }
    feasible = bool(solver_valid and checks["gray"] and checks["connected"] and checks["stress"])
    unmet_targets = [name for name, ok in
                     (("gray", checks["gray"]), ("connected", checks["connected"]),
                      ("stress", checks["stress"])) if not ok]
    if solver_valid and feasible:
        summary = "All configured topology targets passed."
        next_action = "PROMOTE_OR_REPORT"
    elif not solver_valid:
        summary = "The solver result did not pass numerical evaluation."
        next_action = "RETRY_OR_REVISE"
    elif not checks["connected"]:
        summary = ("Solver converged with valid metrics, but the topology is disconnected; "
                   "the target gap is the next optimization direction, not a failure.")
        next_action = "RESTORE_CONNECTIVITY"
    elif not checks["gray"]:
        summary = ("Solver converged with valid metrics; grayness remains above the target. "
                   "The gap is tracked as an optimization direction across Steps, not a failure.")
        next_action = "REDUCE_GRAYNESS"
    else:
        summary = ("Solver converged with valid metrics; the stress margin target is not met. "
                   "Refine at higher fidelity.")
        next_action = "PROMOTE_OR_REPORT"
    return {"success": solver_valid, "feasible": feasible, "unmet_targets": unmet_targets,
            "checks": checks,
            "targets": {"gray_max": gray_limit, "connected": needs_connected,
                        "allowable_stress_mpa": allowable_stress},
            "summary": summary,
            "volume_error": volume_error,
            "maximum_von_mises": maximum_stress,
            "stress_unit": quality.get("stress_unit"),
            "stress_unit_trusted": stress_unit_trusted,
            "allowable_stress_mpa": allowable_stress,
            "stress_margin": (None if allowable_stress is None or not stress_unit_trusted
                              or maximum_stress is None else
                              float(allowable_stress) - float(maximum_stress)),
            "next_action": next_action}
