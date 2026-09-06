def detect_failure(result: dict, constraints: dict) -> dict | None:
    if result.get("status") in {"failed", "timeout"}:
        return {"type": "INFRASTRUCTURE", "evidence": result.get("solver", {})}
    quality = result.get("quality", {})
    target = constraints.get("volume_fraction")
    actual = result.get("constraints", {}).get("volume_fraction")
    if target is not None and actual is not None and abs(float(actual) - float(target)) > float(constraints.get("volume_tolerance", .02)):
        return {"type": "VOLUME_VIOLATION", "evidence": {"target": target, "actual": actual}}
    if constraints.get("connected", True) and quality.get("connected_components", 0) != 1:
        return {"type": "DISCONNECTION", "evidence": {
            "connected_components": quality.get("connected_components")}}
    if quality.get("gray_ratio", 1) > constraints.get("gray_max", 0.05):
        return {"type": "HIGH_GRAY", "evidence": {"gray_ratio": quality.get("gray_ratio")}}
    history = result.get("artifacts", {}).get("history", [])
    if len(history) >= 8:
        changes = [float(item.get("change", 0)) for item in history[-8:]]
        if min(changes) > .05 and max(changes) - min(changes) < .02:
            return {"type": "OSCILLATION", "evidence": {"recent_changes": changes}}
    return None
