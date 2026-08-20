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
    verdict = "SUCCESS" if evaluation["success"] else "PARTIAL SUCCESS"
    return (f"Compliance: {compliance}\n\nGray ratio: {gray}\n\n"
            f"Connected components: {components}\n\nResult: {verdict}\n\n{evaluation['summary']}")

