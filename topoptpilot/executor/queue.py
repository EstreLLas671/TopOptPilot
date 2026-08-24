"""Process-based FEM queue with disk progress snapshots.

The worker never mutates research state. It only returns a solver result and
writes a replaceable progress file; ResearchService owns all state transitions.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_suffix(f".{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, default=_json_default), encoding="utf-8")
    os.replace(temp, path)


def _validate_queue_backend(backend: str) -> None:
    if backend == "simulate":
        raise ValueError("backend=simulate is forbidden for the formal experiment queue")
    if backend not in {"python", "python3d"}:
        raise ValueError(
            f"backend={backend} is not allowed in the formal experiment queue"
        )


def _run_solver(task: dict[str, Any], backend: str, progress_path: str) -> dict[str, Any]:
    _validate_queue_backend(backend)
    target = Path(progress_path)

    def progress(iteration: int, state: dict[str, Any]) -> None:
        payload = {"iteration": iteration, **state}
        _atomic_json(target, payload)

    if backend == "python3d":
        from solver.topopt3d import run_topopt3d
        return run_topopt3d(task, progress=progress)
    from solver.topopt_engine import run_topopt
    return run_topopt(task, backend=backend, progress=progress)


def _json_default(value: Any):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


class ExperimentQueue:
    def __init__(self, progress_dir: str | Path, max_workers: int = 2):
        self.progress_dir = Path(progress_dir).resolve()
        self.progress_dir.mkdir(parents=True, exist_ok=True)
        self._pool = ProcessPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future] = {}
        self._paths: dict[str, Path] = {}
        self._lock = threading.RLock()

    def submit(self, task: dict[str, Any], backend: str = "python",
               done: Callable[[str, Future], None] | None = None) -> str:
        _validate_queue_backend(backend)
        run_id = f"run_{uuid.uuid4().hex[:10]}"
        path = self.progress_dir / f"{run_id}.json"
        _atomic_json(path, {"iteration": 0, "status": "WAITING"})
        future = self._pool.submit(_run_solver, task, backend, str(path))
        with self._lock:
            self._futures[run_id] = future
            self._paths[run_id] = path
        if done:
            future.add_done_callback(lambda current: done(run_id, current))
        return run_id

    def poll(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            future, path = self._futures.get(run_id), self._paths.get(run_id)
        progress: dict[str, Any] = {}
        if path and path.exists():
            try:
                progress = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        if future is None:
            return {"run_id": run_id, "status": "UNKNOWN", **progress}
        if future.cancelled():
            status = "CANCELLED"
        elif future.done():
            status = "FAILED" if future.exception() else "SUCCESS"
        elif future.running():
            status = "RUNNING"
        else:
            status = "WAITING"
        return {"run_id": run_id, **progress, "status": status}

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
        return bool(future and future.cancel())

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=True)
