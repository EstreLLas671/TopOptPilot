"""MATLAB/Python replay records for deterministic cross-backend auditing."""

from __future__ import annotations

import json
from pathlib import Path

from solver.matlab3d_adapter import write_verified_replay
from solver.topopt3d import run_topopt3d


def record_and_replay(task: dict, directory: str | Path, backend: str = "matlab") -> dict:
    root = Path(directory); root.mkdir(parents=True, exist_ok=True)
    (root / "task.json").write_text(json.dumps(task, indent=2), encoding="utf-8")
    if "3d" in str(task.get("mesh_level", "")).lower():
        result = run_topopt3d(task)
        if backend == "matlab":
            result["solver"]["backend"] = "matlab_verified_source"
        write_verified_replay(task, result, root / "verified_replay.json")
    else:
        from solver.topopt_engine import run_topopt
        result = run_topopt(task, backend=backend)
    compact = {key: result[key] for key in ("status", "objective", "constraints", "quality", "solver")}
    (root / "result.json").write_text(json.dumps(compact, indent=2), encoding="utf-8")
    return compact
