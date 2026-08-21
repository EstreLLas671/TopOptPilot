from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


class ResultCache:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(task: dict) -> str:
        canonical = {key: value for key, value in task.items()
                     if key not in {"task_id", "experiment_group", "hypothesis_id"}}
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:24]

    def get(self, task: dict) -> dict | None:
        path = self.directory / f"{self.key(task)}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, task: dict, result: dict) -> Path:
        path = self.directory / f"{self.key(task)}.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, default=lambda value: value.tolist()
                                   if isinstance(value, np.ndarray) else str(value)), encoding="utf-8")
        temp.replace(path)
        return path
