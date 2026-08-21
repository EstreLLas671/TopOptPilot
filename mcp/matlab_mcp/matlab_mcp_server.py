"""Single-session MATLAB MCP worker and ExperimentResult adapter."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np

from solver.result_schema import connected_components, gray_ratio
from .matlab_connector import MatlabConnector, MatlabMcpError


class MatlabMcpWorker:
    def __init__(self, data_dir: str | Path, project_root: str | Path | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.root = Path(project_root or Path(__file__).parents[2]).resolve()
        self.connector = MatlabConnector(self.root, job_root=self.data_dir)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matlab-mcp")
        self._lock = threading.RLock()

    def submit(self, task: dict[str, Any], research_id: str, experiment_id: str,
               done: Callable[[str, Future], None] | None = None) -> tuple[str, Future]:
        run_id = f"matlab_mcp_{experiment_id.lower()}"
        future = self.pool.submit(self.run, task, research_id, experiment_id)
        if done:
            future.add_done_callback(lambda current: done(run_id, current))
        return run_id, future

    def run(self, task: dict[str, Any], research_id: str, experiment_id: str) -> dict[str, Any]:
        job_dir = (self.data_dir / research_id / "matlab_mcp" / experiment_id).resolve()
        if self.data_dir not in job_dir.parents:
            raise MatlabMcpError("MATLAB job path escaped the research data directory")
        job_dir.mkdir(parents=True, exist_ok=True)
        dimension = 3 if "3d" in str(task.get("mesh_level", "")).lower() else 2
        payload = {"dimension": dimension, "config": self._config(task, dimension),
                   "task_id": task.get("task_id")}
        task_path, result_path = job_dir / "task.json", job_dir / "raw_result.json"
        task_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        raw = self.connector.call_topopt(task_path, result_path)
        return self._normalize(raw, task, dimension, task_path, result_path)

    @staticmethod
    def _config(task: dict[str, Any], dimension: int) -> dict[str, Any]:
        params = dict(task.get("params") or {})
        config: dict[str, Any] = {
            "bc_type": task.get("load_case") or "cantilever",
            "volfrac": float(params.get("volfrac", .4)),
            "penal": float(params.get("penal", 3.0)),
            "rmin": float(params.get("rmin", 1.5)),
            "max_iterations": min(int(params.get("max_iter", 80)), 250),
            "min_iterations": min(10, int(params.get("max_iter", 80))),
            "display": False, "verbose": False,
            "bc_config": dict(task.get("bc_config") or {}),
            "geometry": task.get("geometry") or {},
        }
        config["bc_config"].setdefault("load_scale", 1.0)
        if dimension == 3:
            grid = params.get("grid3d") or ([12, 4, 3] if task.get("mesh_level") == "coarse3d"
                                             else [18, 6, 4])
            config.update({"nelx": int(grid[0]), "nely": int(grid[1]), "nelz": int(grid[2]),
                           "accuracy": "standard" if task.get("mesh_level") == "coarse3d" else "high",
                           "penal_start": 1.0, "auto_boundary_solid": False})
        else:
            from solver.params import normalize_task
            spec = normalize_task(task)
            config.update({"nelx": int(spec["nelx"]), "nely": int(spec["nely"])})
        if not (.1 <= config["volfrac"] <= .7 and .75 <= config["rmin"] <= 4
                and 1 <= config["penal"] <= 5):
            raise MatlabMcpError("Task escaped the approved MATLAB parameter envelope")
        return config

    def _normalize(self, raw: dict[str, Any], task: dict[str, Any], dimension: int,
                   task_path: Path, result_path: Path) -> dict[str, Any]:
        density = np.asarray(raw.get("density"), dtype=float)
        compliance = float(raw.get("compliance", math.nan))
        if density.ndim != dimension or density.size == 0 or not np.all(np.isfinite(density)):
            raise MatlabMcpError("MATLAB returned an invalid density field")
        if not math.isfinite(compliance):
            raise MatlabMcpError("MATLAB returned a non-finite compliance")
        objectives = np.asarray(raw.get("objective_history") or [], dtype=float).ravel().tolist()
        changes = np.asarray(raw.get("change_history") or [], dtype=float).ravel().tolist()
        history = [{"iteration": i + 1, "compliance": float(value),
                    "change": float(changes[i]) if i < len(changes) else None}
                   for i, value in enumerate(objectives)]
        entry = (self.root / ("求解器模块/TopOpt-3D/TopOpt-3D/topopt3d_main.m" if dimension == 3 else
                              "求解器模块/2D/TopOpt_integrated/TopOpt_integrated/topopt_main.m"))
        return {
            "run_id": "", "task_id": str(task.get("task_id", "")),
            "hypothesis_id": str(task.get("hypothesis_id", "")),
            "experiment_group": str(task.get("experiment_group", "")), "status": "converged",
            "objective": {"compliance": compliance},
            "constraints": {"volume_fraction": float(raw.get("volume_fraction", density.mean()))},
            "quality": {"gray_ratio": round(float(gray_ratio(density)), 4),
                        "connected_components": int(connected_components(density)),
                        "max_displacement_mm": None},
            "solver": {"backend": f"matlab_mcp_{dimension}d", "matlab_version": raw.get("matlab_version"),
                       "mcp_version": "0.12.0", "solver_entry": raw.get("solver_entry"),
                       "solver_entry_sha256": hashlib.sha256(entry.read_bytes()).hexdigest(),
                       "iterations": int(raw.get("iterations", len(history))),
                       "relative_residual": None},
            "artifacts": {"density": density, "density_design": density, "history": history,
                          "matlab_task": str(task_path), "matlab_raw_result": str(result_path)},
        }

    def health(self) -> dict[str, Any]:
        return self.connector.health()

    def restart(self) -> dict[str, Any]:
        with self._lock:
            return self.connector.restart()

    def configure(self, *, matlab_root: str | Path | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            return self.connector.configure(matlab_root=matlab_root, timeout=timeout)

    def close(self) -> None:
        self.connector.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
