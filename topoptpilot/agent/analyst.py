from __future__ import annotations

from typing import Any


def build_analysis(result: dict[str, Any], evaluation: dict[str, Any]) -> str:
    objective = result.get("objective", {})
    quality = result.get("quality", {})
    compliance = objective.get("compliance", "—")
    gray = quality.get("gray_ratio", "—")
    components = quality.get("connected_components", "—")
    if isinstance(gray, (int, float)):
        gray = f"{gray:.1%}"
    checks = evaluation.get("checks", {})
    targets = evaluation.get("targets", {})
    gray_target = targets.get("gray_max")
    gaps = []
    if checks.get("gray") is False:
        limit = f"{gray_target:.1%}" if isinstance(gray_target, (int, float)) else "reference"
        gaps.append(f"grayness {gray} vs target ≤ {limit}")
    if checks.get("connected") is False:
        gaps.append(f"topology splits into {components} parts vs target 1")
    if checks.get("stress") is False:
        gaps.append("von Mises stress above the allowable reference")
    verdict = ("SUCCESS" if evaluation.get("feasible")
               else "CONVERGED" if evaluation.get("success") else "PARTIAL SUCCESS")
    lines = [f"Compliance: {compliance}",
             f"Gray ratio: {gray}",
             f"Connected components: {components}"]
    if gaps:
        lines.append("Target gaps (review criteria, optimization directions — not failures): "
                     + "; ".join(gaps))
    lines.append(f"Result: {verdict}")
    lines.append(evaluation["summary"])
    return "\n\n".join(lines)

