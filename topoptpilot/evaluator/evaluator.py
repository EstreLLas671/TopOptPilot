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
    volume_error = (None if target_volume is None or actual_volume is None else
                    float(actual_volume) - float(target_volume))
    checks = {
        "gray": gray <= gray_limit,
        "connected": (components == 1) if needs_connected else True,
        "finite_compliance": compliance is not None and math.isfinite(float(compliance)),
        "volume": volume_error is None or abs(volume_error) <= float(constraints.get("volume_tolerance", .02)),
    }
    success = all(checks.values()) and result.get("status") not in {"failed", "timeout"}
    if success:
        summary = "All configured topology constraints passed."
        next_action = "PROMOTE_OR_REPORT"
    elif not checks["connected"]:
        summary = "Grayness may have improved, but the topology is disconnected."
        next_action = "RESTORE_CONNECTIVITY"
    elif not checks["gray"]:
        summary = "The topology remains above the configured gray-ratio limit."
        next_action = "REDUCE_GRAYNESS"
    else:
        summary = "The solver result did not pass numerical evaluation."
        next_action = "RETRY_OR_REVISE"
    return {"success": success, "checks": checks, "summary": summary,
            "volume_error": volume_error,
            "next_action": next_action}
