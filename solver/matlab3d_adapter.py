"""Verified replay helper; live F3 execution is exclusively MATLAB MCP."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path



def canonical_task_hash(task: dict) -> str:
    payload = {key: value for key, value in task.items()
               if key not in {"task_id", "experiment_group", "hypothesis_id"}}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_matlab3d_or_replay(task: dict, progress=None) -> dict:
    replay_path = os.getenv("TOPPILOT_F3_REPLAY")
    if replay_path:
        record = json.loads(Path(replay_path).read_text(encoding="utf-8"))
        expected = canonical_task_hash(task)
        if record.get("task_hash") != expected:
            raise ValueError("F3 replay task hash mismatch; refusing unrelated evidence")
        result = record.get("result")
        if not isinstance(result, dict) or not result.get("quality") or not result.get("objective"):
            raise ValueError("F3 replay is not a complete verified result")
        result.setdefault("solver", {})["backend"] = "matlab_verified_replay_3d"
        result["solver"]["replay_task_hash"] = expected
        return result
    raise RuntimeError("F3 requires a live approved MatlabMcpWorker; Python fallback is forbidden")


def write_verified_replay(task: dict, result: dict, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"task_hash": canonical_task_hash(task), "result": result},
                                 default=lambda value: value.tolist()
                                 if hasattr(value, "tolist") else str(value)), encoding="utf-8")
    return target
