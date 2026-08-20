def flatten_metrics(result: dict) -> dict:
    return {**result.get("objective", {}), **result.get("constraints", {}),
            **result.get("quality", {}), "runtime_seconds":
            result.get("solver", {}).get("solve_time_seconds")}

