"""Re-run a reproduction bundle's completed experiments without an LLM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from solver.matlab3d_adapter import run_matlab3d_or_replay
from solver.topopt3d import run_topopt3d
from solver.topopt_engine import run_topopt
from topoptpilot.executor.executor import build_solver_task


def replay_research(path: str | Path) -> dict:
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    outputs = []
    by_id = {item["id"]: item for item in source.get("experiments", [])}
    for experiment in source.get("experiments", []):
        if not experiment.get("result"): continue
        task = build_solver_task(experiment, source)
        if experiment.get("warm_start"):
            warm = by_id.get(experiment["warm_start"], {})
            density = (warm.get("result") or {}).get("artifacts", {}).get("density")
            if density is not None: task["params"]["initial_density"] = density
        if experiment["backend"] == "python3d": result = run_topopt3d(task)
        elif experiment["backend"] == "matlab" and "3d" in experiment["mesh_level"]:
            result = run_matlab3d_or_replay(task)
        else: result = run_topopt(task, backend=experiment["backend"])
        expected = experiment["result"]["objective"].get("compliance")
        actual = result["objective"].get("compliance")
        outputs.append({"experiment_id": experiment["id"], "expected": expected, "actual": actual,
                        "relative_error": abs(actual - expected) / max(abs(expected), 1e-12)})
    return {"research_id": source.get("id"), "replayed": outputs,
            "all_deterministic": all(item["relative_error"] < 1e-8 for item in outputs)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("research_json")
    parser.add_argument("--output", default="replay_result.json")
    args = parser.parse_args()
    result = replay_research(args.research_json)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["all_deterministic"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
