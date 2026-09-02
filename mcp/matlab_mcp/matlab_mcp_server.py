"""Single-session MATLAB MCP worker and ExperimentResult adapter."""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np

from solver.result_schema import connected_components, gray_ratio
from .matlab_connector import MatlabConnector, MatlabMcpError
from .gateway import MatlabGateway


class MatlabMcpWorker:
    def __init__(self, data_dir: str | Path, project_root: str | Path | None = None):
        self.data_dir = Path(data_dir).resolve()
        self.root = Path(project_root or Path(__file__).parents[2]).resolve()
        self.connector = MatlabConnector(self.root, job_root=self.data_dir)
        self.gateway = MatlabGateway(self.connector, self.data_dir)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="matlab-mcp")
        self._lock = threading.RLock()
        self._capability_cache: dict[str, Any] = {
            "variants": ["reference_cpu", "optimized_cpu"], "selected_variant": "optimized_cpu",
            "acceleration_mode": "vectorized_cpu", "parallel_available": None,
            "gpu_available": None, "mex_2d_available": False, "mex_3d_available": False,
            "probed": False,
        }
        self._warmup: dict[str, Any] | None = None
        self._run_stats: list[dict[str, Any]] = []
        self._futures: dict[str, Future] = {}

    def submit(self, task: dict[str, Any], research_id: str, experiment_id: str,
               done: Callable[[str, Future], None] | None = None) -> tuple[str, Future]:
        run_id = f"run_matlab_mcp_{experiment_id.lower()}"
        future = self.pool.submit(self.run, task, research_id, experiment_id)
        with self._lock:
            self._futures[run_id] = future
        if done:
            future.add_done_callback(lambda current: done(run_id, current))
        return run_id, future

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
        if not future:
            return False
        if future.cancel():
            return True
        if future.running():
            self.connector.stop()
            return True
        return future.done()

    def wait_for_stop(self, run_id: str, timeout: float = 15.0) -> bool:
        with self._lock:
            future = self._futures.get(run_id)
        if future is None:
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.05)
        return future.done()

    def run(self, task: dict[str, Any], research_id: str, experiment_id: str) -> dict[str, Any]:
        job_dir = (self.data_dir / research_id / "matlab_mcp" / experiment_id).resolve()
        if self.data_dir not in job_dir.parents:
            raise MatlabMcpError("MATLAB job path escaped the research data directory")
        job_dir.mkdir(parents=True, exist_ok=True)
        fidelity = str(task.get("fidelity", "F0")).upper()
        dimension = 3 if fidelity in {"F2", "F3"} or "3d" in str(task.get("mesh_level", "")).lower() else 2
        payload = {"dimension": dimension, "config": self._config(task, dimension),
                   "task_id": task.get("task_id"), "operation": "solve"}
        task_path, result_path = job_dir / "task.json", job_dir / "raw_result.json"
        task_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        scheduled_at = time.monotonic()
        raw = self.gateway.run_topopt_task(task_path, result_path)
        if isinstance(raw.get("capabilities"), dict):
            self._capability_cache.update(raw["capabilities"])
            self._capability_cache["probed"] = True
        result = self._normalize(raw, task, dimension, task_path, result_path)
        self._run_stats.append({
            "research_id": research_id, "experiment_id": experiment_id,
            "dimension": dimension,
            "variant": raw.get("solver_variant") or result.get("solver", {}).get("solver_variant"),
            "elapsed_seconds": round(time.monotonic() - scheduled_at, 3),
            "iterations": result.get("solver", {}).get("iterations"),
        })
        self._run_stats[:] = self._run_stats[-20:]
        return result

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
            "E": float(params.get("E", 1.0)),
            "verification_mode": str(params.get("verification_mode", "")),
            "initial_density": params.get("initial_density"),
            "nu": float(params.get("nu", 0.3)),
            "beta": float(params.get("beta", 1.0)),
            "solver_variant": str(task.get("solver_variant", "auto")),
            "acceleration_mode": str(task.get("acceleration_mode", "auto")),
        }
        config["bc_config"].setdefault("load_scale", 1.0)
        geometry = config["geometry"]
        if isinstance(geometry, dict) and geometry.get("mask") is not None:
            config["domain_mask"] = geometry["mask"]
        if dimension == 3:
            grid = params.get("grid3d")
            if str(params.get("verification_mode", "")) == "fixed_density" and not (isinstance(grid, (list, tuple)) and len(grid) == 3):
                raise MatlabMcpError("F3 fixed-density verification requires an explicit grid3d")
            grid = grid or ([12, 4, 3] if task.get("mesh_level") == "coarse3d"
                            else [18, 6, 4])
            if not isinstance(grid, (list, tuple)) or len(grid) != 3 or any(int(value) < 1 for value in grid):
                raise MatlabMcpError("grid3d must contain three positive integers")
            config.update({"nelx": int(grid[0]), "nely": int(grid[1]), "nelz": int(grid[2]),
                           "accuracy": "standard" if task.get("mesh_level") == "coarse3d" else "high",
                           "penal_start": 1.0, "auto_boundary_solid": False})
        else:
            from solver.params import normalize_task
            spec = normalize_task(task)
            config.update({"nelx": int(spec["nelx"]), "nely": int(spec["nely"])})
        if "domain_mask" in config:
            mask_shape = np.asarray(config["domain_mask"]).shape
            if dimension == 2 and len(mask_shape) == 2:
                config.update({"nely": int(mask_shape[0]), "nelx": int(mask_shape[1])})
            elif dimension == 3 and len(mask_shape) == 3:
                config.update({"nely": int(mask_shape[0]), "nelx": int(mask_shape[1]),
                               "nelz": int(mask_shape[2])})
            else:
                raise MatlabMcpError(f"Custom mask must have {dimension} dimensions")
        if not (.1 <= config["volfrac"] <= .7 and .75 <= config["rmin"] <= 4
                and 1 <= config["penal"] <= 5 and config["E"] > 0
                and 0 <= config["nu"] < .5 and 1 <= config["beta"] <= 64):
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
        stress = None
        stress_error = None
        raw_stress = raw.get("von_mises")
        if raw_stress is None:
            stress_error = "MATLAB 未返回 Von Mises 应力场"
        else:
            candidate = np.asarray(raw_stress, dtype=float)
            if candidate.shape != density.shape or candidate.size == 0 or not np.all(np.isfinite(candidate)):
                stress_error = "MATLAB Von Mises 应力场形状或有限性校验失败"
            else:
                stress = candidate
        from solver.stress import stress_unit_metadata
        unit_metadata = stress_unit_metadata(task)
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
                        "max_displacement_mm": None,
                        "maximum_von_mises": (float(np.max(stress)) if stress is not None else None),
                        **unit_metadata,
                        "stress_unavailable_reason": stress_error},
            "solver": {"backend": f"matlab_mcp_{dimension}d", "matlab_version": raw.get("matlab_version"),
                       "mcp_version": self.gateway.health().get("server_version"),
                       "mcp_binary_sha256": self.gateway.health().get("binary_sha256"),
                       "task_sha256": hashlib.sha256(task_path.read_bytes()).hexdigest(),
                       "solver_entry": raw.get("solver_entry"),
                       "solver_entry_sha256": hashlib.sha256(entry.read_bytes()).hexdigest(),
                       "solver_variant": raw.get("solver_variant", "optimized_cpu"),
                       "acceleration_mode": raw.get("acceleration_mode", "vectorized_cpu"),
                       "capabilities": raw.get("capabilities", self._capability_cache),
                       "iterations": int(raw.get("iterations", len(history))),
                       "relative_residual": None},
            "artifacts": {"density": density, "density_design": density, "stress": stress, "history": history,
                          "matlab_task": str(task_path), "matlab_raw_result": str(result_path)},
        }

    def health(self) -> dict[str, Any]:
        health = self.gateway.health()
        health["startup_ms"] = getattr(self.connector, "startup_ms", None)
        health["warmup"] = self._warmup
        health["last_runs"] = list(self._run_stats[-5:])
        return health

    def warmup(self) -> dict[str, Any]:
        """Cold-start the MCP process and MATLAB session, then probe capabilities.

        Warmup deliberately runs only the capabilities probe — it never executes a
        solver iteration — so first experiment latency excludes MATLAB startup cost.
        """
        with self._lock:
            started_at = time.monotonic()
            self.connector.start()
            cold_start_ms = round((time.monotonic() - started_at) * 1000)
            probe_started = time.monotonic()
            capabilities = self.capabilities(probe=True)
            probe_ms = round((time.monotonic() - probe_started) * 1000)
            self._warmup = {
                "cold_start_ms": cold_start_ms,
                "probe_ms": probe_ms,
                "mcp_startup_ms": getattr(self.connector, "startup_ms", None),
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "capabilities": capabilities,
            }
            return dict(self._warmup)

    def capabilities(self, *, probe: bool = False) -> dict[str, Any]:
        if probe:
            job_dir = (self.data_dir / "_system" / "matlab_capabilities").resolve()
            job_dir.mkdir(parents=True, exist_ok=True)
            task_path, result_path = job_dir / "task.json", job_dir / "result.json"
            payload = {"operation": "capabilities", "dimension": 2,
                       "config": {"volfrac": .4, "rmin": 1.5, "penal": 3.0}}
            task_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            raw = self.gateway.run_topopt_task(task_path, result_path)
            if isinstance(raw.get("capabilities"), dict):
                self._capability_cache.update(raw["capabilities"])
                self._capability_cache["probed"] = True
        return dict(self._capability_cache)

    def preview_geometry(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return only MATLAB-generated mask/support/load mappings; never run FEM."""
        dimension = int(request.get("dimension", 2))
        if dimension not in {2, 3}:
            raise MatlabMcpError("Geometry preview dimension must be 2 or 3")
        grid = request.get("grid") or ([48, 16] if dimension == 2 else [18, 6, 4])
        if len(grid) != dimension or any(int(value) < 2 or int(value) > 240 for value in grid):
            raise MatlabMcpError("Geometry preview grid is outside the controlled envelope")
        config = {
            "bc_type": str(request.get("bc_type") or "MBB"),
            "geometry": request.get("geometry") or {},
            "bc_config": {"load_scale": float(request.get("load_scale", 1.0))},
            "volfrac": .4, "rmin": 1.5, "penal": 3.0,
            "nelx": int(grid[0]), "nely": int(grid[1]),
        }
        if dimension == 3:
            config["nelz"] = int(grid[2])
        mask = request.get("mask")
        if mask is not None:
            array = np.asarray(mask)
            expected = (config["nely"], config["nelx"]) if dimension == 2 else (config["nely"], config["nelx"], config["nelz"])
            if array.shape != expected or array.size > 250_000:
                raise MatlabMcpError(f"Custom mask must have MATLAB shape {expected}")
            if not np.isin(array, [0, 1, False, True]).all():
                raise MatlabMcpError("Custom mask may contain only zero/one values")
            config["domain_mask"] = array.astype(bool).tolist()
        job_dir = (self.data_dir / "_system" / "geometry_preview" / uuid.uuid4().hex).resolve()
        job_dir.mkdir(parents=True, exist_ok=True)
        task_path, result_path = job_dir / "task.json", job_dir / "result.json"
        task_path.write_text(json.dumps({"operation": "preview_geometry", "dimension": dimension,
                                         "config": config}, ensure_ascii=False), encoding="utf-8")
        return self.gateway.run_topopt_task(task_path, result_path)

    def restart(self) -> dict[str, Any]:
        with self._lock:
            health = self.connector.restart()
            try:
                self.capabilities(probe=True)
            except Exception as exc:
                self._capability_cache["probe_error"] = str(exc)
            return {**health, "capabilities": self.capabilities(probe=False)}

    def configure(self, *, matlab_root: str | Path | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
        with self._lock:
            return self.connector.configure(matlab_root=matlab_root, timeout=timeout)

    def close(self) -> None:
        self.connector.stop()
        # Stop callbacks before the owning research directory is removed.
        self.pool.shutdown(wait=True, cancel_futures=True)
