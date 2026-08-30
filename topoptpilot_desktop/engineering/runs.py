"""工程求解任务、制品和进度流管理。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from topoptpilot_desktop.artifacts.models import ArtifactRef, ErrorEnvelope, ErrorSource, OwnerType, RunArtifact, RunStatus, SolverLane
from topoptpilot_desktop.engineering.artifact_index import discover_artifact_files, media_type_for
from topoptpilot_desktop.engineering.external_summary import normalize_external_summary
from topoptpilot_desktop.engineering.matlab import discover_matlab_installations, probe_matlab_installation
from topoptpilot_desktop.engineering.matlab_runner import MatlabInfrastructureError, build_runtime_command, run_matlab_batch, run_runtime_solver
from topoptpilot_desktop.engineering.runtime_profiles import RuntimeProfileError, runtime_profiles, stage_runtime_solver


def _data_root() -> Path:
    root = os.environ.get("TOPOPTPILOT_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TopOptPilot"
    return (Path(root).expanduser().resolve() if root else local) / "runs"


def engineering_matlab_source_root() -> Path:
    resource_root = os.environ.get("TOPPILOT_RESOURCE_ROOT")
    if resource_root:
        return Path(resource_root).resolve() / "matlab" / "engineering"
    return Path(__file__).resolve().parents[2] / "matlab" / "engineering"


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane: SolverLane
    runtime_profile_id: str | None = Field(default=None, min_length=1, max_length=160)
    owner_id: str = Field(default="engineering", min_length=1, max_length=160)
    task: dict[str, Any] = Field(default_factory=dict)
    max_iter: int | None = Field(default=None, ge=1, le=2000)
    time_limit: float | None = Field(default=None, ge=0.1, le=86400)

    @model_validator(mode="before")
    @classmethod
    def accept_camel_case(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            value.setdefault("owner_id", value.pop("ownerId", "engineering"))
            value.setdefault("max_iter", value.pop("maxIter", None))
            value.setdefault("time_limit", value.pop("timeLimit", None))
            value.setdefault("runtime_profile_id", value.pop("runtimeProfileId", None))
        return value

    @model_validator(mode="after")
    def validate_runtime_profile_scope(self):
        if self.lane is not SolverLane.COMPILED_RUNTIME and self.runtime_profile_id:
            raise ValueError(
                "runtimeProfileId 只能用于 compiled-runtime lane"
            )

        task = self.task
        dimension = str(task.get("dimension") or "3d").lower()
        if dimension not in {"2d", "3d"}:
            raise ValueError("task.dimension 仅支持 2d 或 3d")
        geometry = task.get("geometry") or {}
        params = task.get("params") or {}
        material = task.get("material") or {}
        if not isinstance(geometry, dict) or not isinstance(params, dict) or not isinstance(material, dict):
            raise ValueError("task.geometry、task.params 和 task.material 必须是对象")
        material_preset = material.get("preset")
        if material_preset is not None and material_preset not in {"normalized", "structural-steel", "aluminum-6061-t6", "titanium-ti6al4v", "custom"}:
            raise ValueError("材料 preset 不是受支持的预设")
        material_name = material.get("name")
        if material_name is not None and (not isinstance(material_name, str) or not material_name.strip() or len(material_name.strip()) > 80):
            raise ValueError("材料名称必须为 1–80 个字符")
        if material_preset == "custom" and any(key not in material for key in ("name", "density_kg_m3", "yield_strength_MPa")):
            raise ValueError("自定义材料必须包含名称、密度和屈服强度")
        load_case = str(task.get("load_case") or "cantilever")
        if load_case not in {"cantilever", "MBB", "mbb", "simply_supported", "L-bracket", "vertical", "lateral"}:
            raise ValueError("load_case 不是受支持的内置工况")
        for key in ("nelx", "nely", "nelz"):
            if key in geometry and (isinstance(geometry[key], bool) or not isinstance(geometry[key], int) or geometry[key] <= 0):
                raise ValueError(f"geometry.{key} 必须是正整数")
        volfrac = params.get("volfrac")
        if volfrac is not None and not 0 < float(volfrac) <= 1:
            raise ValueError("volfrac 必须大于 0 且不超过 1")
        penal = params.get("penal")
        if penal is not None and float(penal) < 1:
            raise ValueError("penal 必须不小于 1")
        rmin = params.get("rmin")
        if rmin is not None and float(rmin) <= 0:
            raise ValueError("rmin 必须大于 0")
        youngs_modulus = params.get("E", material.get("E", material.get("E_GPa")))
        poisson_ratio = params.get("nu", material.get("nu"))
        density = material.get("density_kg_m3")
        yield_strength = material.get("yield_strength_MPa")
        if youngs_modulus is not None and (isinstance(youngs_modulus, bool) or not math.isfinite(float(youngs_modulus)) or float(youngs_modulus) <= 0):
            raise ValueError("材料杨氏模量 E 必须大于 0")
        if poisson_ratio is not None and (isinstance(poisson_ratio, bool) or not math.isfinite(float(poisson_ratio)) or not -1 < float(poisson_ratio) < 0.5):
            raise ValueError("材料泊松比 nu 必须大于 -1 且小于 0.5")
        if density is not None and (isinstance(density, bool) or not math.isfinite(float(density)) or float(density) <= 0):
            raise ValueError("材料密度 density_kg_m3 必须大于 0")
        if yield_strength is not None and (isinstance(yield_strength, bool) or not math.isfinite(float(yield_strength)) or float(yield_strength) <= 0):
            raise ValueError("材料屈服强度 yield_strength_MPa 必须大于 0")
        max_iterations = int(params.get("max_iter", self.max_iter or 60))
        min_iterations = int(params.get("min_iter", 1))
        if min_iterations < 1 or max_iterations < 1 or min_iterations > max_iterations:
            raise ValueError("迭代范围无效：必须满足 1 <= min_iter <= max_iter")
        if params.get("filter_strategy", "fixed") not in {"fixed", "adaptive"}:
            raise ValueError("filter_strategy 仅支持 fixed 或 adaptive")
        if params.get("accuracy", "standard") not in {"standard", "high"}:
            raise ValueError("accuracy 仅支持 standard 或 high")
        return self

@dataclass
class _Run:
    run_id: str
    owner_id: str
    lane: SolverLane
    task: dict[str, Any]
    config_digest: str
    run_dir: Path
    runtime_profile_id: str | None = None
    status: RunStatus = RunStatus.QUEUED
    metrics: dict[str, float | None] = field(default_factory=dict)
    snapshots: list[ArtifactRef] = field(default_factory=list)
    files: list[ArtifactRef] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    error: ErrorEnvelope | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def public(self) -> dict[str, Any]:
        return RunArtifact(
            runId=self.run_id,
            ownerType=OwnerType.ENGINEERING_RUN,
            ownerId=self.owner_id,
            lane=self.lane,
            status=self.status,
            configDigest=self.config_digest,
            metrics=self.metrics,
            snapshots=self.snapshots,
            files=self.files,
            provenance=self.provenance,
            error=self.error,
        ).model_dump(by_alias=True, mode="json")


class RunManager:
    def __init__(self) -> None:
        self._runs: dict[str, _Run] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _manifest_path(run_dir: Path) -> Path:
        return run_dir / "run-manifest.json"

    def persist(self, record: _Run) -> None:
        with record.lock:
            payload = {
                "schemaVersion": 1,
                "run": record.public(),
                "task": record.task,
                "runtimeProfileId": record.runtime_profile_id,
                "events": list(record.events),
            }
            target = self._manifest_path(record.run_dir)
            temporary = target.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(target)

    def _load(self, run_id: str) -> _Run | None:
        if not re.fullmatch(r"eng-[0-9a-f]{32}", run_id):
            return None
        root = _data_root().resolve()
        run_dir = (root / run_id).resolve()
        if root not in run_dir.parents:
            return None
        manifest = self._manifest_path(run_dir)
        if not manifest.is_file():
            return None
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            if payload.get("schemaVersion") != 1:
                return None
            artifact = RunArtifact.model_validate(payload["run"])
            if artifact.run_id != run_id:
                return None
            record = _Run(
                run_id=artifact.run_id, owner_id=artifact.owner_id, lane=artifact.lane,
                task=dict(payload.get("task") or {}), config_digest=artifact.config_digest,
                run_dir=run_dir, runtime_profile_id=payload.get("runtimeProfileId"),
                status=artifact.status, metrics=dict(artifact.metrics),
                snapshots=list(artifact.snapshots), files=list(artifact.files),
                provenance=dict(artifact.provenance), error=artifact.error,
                events=list(payload.get("events") or []),
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None
        if record.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
            record.status = RunStatus.FAILED
            record.error = ErrorEnvelope(
                code="RUN_INTERRUPTED", source=ErrorSource.ENGINEERING,
                message="应用退出时运行尚未完成；历史记录已恢复为失败状态。",
                retryable=True,
            )
            self.persist(record)
        return record

    def submit(self, request: RunCreateRequest) -> _Run:
        if request.lane is SolverLane.MATLAB_MCP:
            raise ValueError("matlab-mcp 只能通过 ResearchService、Policy、审批和 MATLAB MCP 启动")
        task = json.loads(json.dumps(request.task, ensure_ascii=False))
        if request.max_iter is not None:
            task.setdefault("params", {})["max_iter"] = request.max_iter
        canonical = json.dumps({"lane": request.lane.value, "ownerId": request.owner_id, "runtimeProfileId": request.runtime_profile_id, "task": task}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        run_id = f"eng-{uuid.uuid4().hex}"
        run_dir = _data_root() / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        record = _Run(run_id, request.owner_id, request.lane, task, hashlib.sha256(canonical.encode("utf-8")).hexdigest(), run_dir, runtime_profile_id=request.runtime_profile_id)
        with self._lock:
            self._runs[run_id] = record
        self.persist(record)
        threading.Thread(target=self._worker, args=(record, request.time_limit), daemon=True, name=f"topoptpilot-run-{run_id}").start()
        return record

    def submit_headless_runtime(self, request: RunCreateRequest) -> _Run:
        if request.lane is not SolverLane.COMPILED_RUNTIME or request.runtime_profile_id:
            raise ValueError("headless Runtime 入口只接受未绑定 profile 的 compiled-runtime 请求")
        try:
            profile = runtime_profiles.verify_environment()
        except (RuntimeProfileError, OSError) as exc:
            raise ValueError(str(exc)) from exc
        bound = request.model_copy(update={"runtime_profile_id": profile.profile_id})
        return self.submit(bound)

    def get(self, run_id: str) -> _Run | None:
        with self._lock:
            current = self._runs.get(run_id)
        if current is not None:
            return current
        restored = self._load(run_id)
        if restored is None:
            return None
        with self._lock:
            return self._runs.setdefault(run_id, restored)

    def list(self, owner_id: str | None = None) -> list[_Run]:
        """Restore persisted runs and return newest first without re-running them."""
        root = _data_root()
        try:
            run_ids = [item.name for item in root.iterdir() if item.is_dir()]
        except OSError:
            run_ids = []
        records = [record for run_id in run_ids if (record := self.get(run_id)) is not None]
        if owner_id:
            records = [record for record in records if record.owner_id == owner_id]
        return sorted(
            records,
            key=lambda record: self._manifest_path(record.run_dir).stat().st_mtime,
            reverse=True,
        )

    def cancel(self, run_id: str) -> _Run:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.cancel_event.set()
        with record.lock:
            if record.status is RunStatus.QUEUED:
                record.status = RunStatus.CANCELLED
        self.persist(record)
        return record

    def events(self, run_id: str) -> list[dict[str, Any]]:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        with record.lock:
            return list(record.events)

    def _emit(self, record: _Run, event: dict[str, Any]) -> None:
        with record.lock:
            record.events.append({"seq": len(record.events) + 1, "timestamp": time.time(), **event})
        self.persist(record)

    def _publish_console(self, record: _Run, stream: str, text: str) -> None:
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text).replace("\x00", "")
        clean = re.sub(
            r"(?i)(authorization\s*[:=]\s*bearer\s+|api[_-]?key\s*[:=]\s*|dashscope_api_key\s*[:=]\s*)\S+",
            r"\1[REDACTED]",
            clean,
        )
        if clean:
            self._emit(record, {
                "type": "console",
                "runId": record.run_id,
                "stream": stream if stream in {"stdout", "stderr"} else "stdout",
                "phase": "solver",
                "text": clean[:16384],
            })

    @staticmethod
    def _ref(run_dir: Path, path: Path, media_type: str | None = None) -> ArtifactRef:
        return ArtifactRef(
            relativePath=path.relative_to(run_dir).as_posix(),
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            mediaType=media_type or media_type_for(path),
            sizeBytes=path.stat().st_size,
        )

    def _index_artifacts(self, record: _Run) -> None:
        files, snapshots = discover_artifact_files(record.run_dir)
        with record.lock:
            record.files = [self._ref(record.run_dir, path) for path in files]
            record.snapshots = [self._ref(record.run_dir, path) for path in snapshots]

    def _publish_progress(
        self,
        record: _Run,
        iteration: int,
        state: dict[str, Any],
    ) -> None:
        with record.lock:
            record.metrics.update({
                "iteration": float(iteration),
                "iterations": float(iteration),
                "compliance": float(state["compliance"]) if state.get("compliance") is not None else None,
                "volumeFraction": float(state["volume_fraction"]) if state.get("volume_fraction") is not None else None,
                "grayRatio": float(state["gray_ratio"]) if state.get("gray_ratio") is not None else None,
            })
            metrics = dict(record.metrics)

        event: dict[str, Any] = {
            "type": "progress",
            "iteration": iteration,
            "metrics": metrics,
        }
        raw_snapshot = state.get("snapshot")
        if isinstance(raw_snapshot, dict):
            snapshot_event = {
                key: raw_snapshot.get(key)
                for key in ("densityPath", "stressPath", "renderPath", "shape", "dtype", "order", "dimension")
            }
            indexed: dict[str, ArtifactRef] = {}
            for key in ("densityPath", "stressPath", "renderPath"):
                raw_path = snapshot_event.get(key)
                if not isinstance(raw_path, str) or not raw_path:
                    continue
                relative = Path(raw_path)
                if relative.is_absolute() or not relative.parts or relative.parts[0] != "snapshots":
                    continue
                candidate = (record.run_dir / relative).resolve()
                try:
                    candidate.relative_to(record.run_dir.resolve())
                except ValueError:
                    continue
                if not candidate.is_file():
                    continue
                indexed[key] = self._ref(record.run_dir, candidate)
            if "densityPath" in indexed:
                with record.lock:
                    by_path = {item.relative_path: item for item in record.snapshots}
                    for reference in indexed.values():
                        by_path[reference.relative_path] = reference
                    record.snapshots = sorted(by_path.values(), key=lambda item: item.relative_path)
                snapshot_event["densitySha256"] = indexed["densityPath"].sha256
                if "stressPath" in indexed:
                    snapshot_event["stressSha256"] = indexed["stressPath"].sha256
                if "renderPath" in indexed:
                    snapshot_event["renderSha256"] = indexed["renderPath"].sha256
                event["snapshot"] = snapshot_event
        self._emit(record, event)

    def _worker(self, record: _Run, time_limit: float | None) -> None:
        with record.lock:
            if record.cancel_event.is_set():
                record.status = RunStatus.CANCELLED
                self.persist(record)
                return
            record.status = RunStatus.RUNNING
            record.provenance = {"resultKind": "attempt", "verification": "unverified", "backend": record.lane.value, "lane": record.lane.value}
        self._emit(record, {"type": "status", "status": "running"})
        try:

            started = time.time()

            def progress(iteration: int, state: dict[str, Any]) -> None:
                snapshot = record.run_dir / "snapshots" / f"iteration-{iteration:04d}.json"
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                snapshot.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
                self._publish_progress(record, iteration, state)

            def console(stream: str, text: str) -> None:
                self._publish_console(record, stream, text)


            if record.lane is SolverLane.PYTHON_FEM:
                from solver.topopt_engine import run_topopt
                result = run_topopt(record.task, backend="python", time_limit=time_limit, progress=progress, cancel=record.cancel_event.is_set)
            else:
                result = self._run_external(
                    record,
                    time_limit,
                    progress=lambda iteration, state: self._publish_progress(
                        record, iteration, state
                    ),
                    console=console,
                )
            provenance = result.get("provenance")
            if isinstance(provenance, dict):
                record.provenance = {str(key): str(value) for key, value in provenance.items()}
            elif record.lane is SolverLane.PYTHON_FEM and result.get("status") in {"completed", "converged", "max_iter", "timeout"}:
                record.provenance = {"resultKind": "solver", "backend": record.lane.value, "lane": record.lane.value}
            summary = {
                "runId": record.run_id,
                "status": result.get("status"),
                "objective": result.get("objective"),
                "constraints": result.get("constraints"),
                "quality": result.get("quality"),
                "solver": result.get("solver"),
                "material": record.task.get("material"),
                "provenance": record.provenance,
            }
            (record.run_dir / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
            density_data = result.get("artifacts", {}).get("density")
            if density_data is not None:
                np.savetxt(record.run_dir / "density.csv", np.asarray(density_data, dtype=float), delimiter=",")
            (record.run_dir / "history.json").write_text(json.dumps(result.get("artifacts", {}).get("history", []), ensure_ascii=False, indent=2, default=float), encoding="utf-8")
            self._index_artifacts(record)
            with record.lock:
                record.metrics.update({
                    "iterations": float(result.get("solver", {}).get("iterations", 0)),
                    "compliance": float(result.get("objective", {}).get("compliance")) if result.get("objective", {}).get("compliance") is not None else None,
                    "volumeFraction": float(result.get("constraints", {}).get("volume_fraction")) if result.get("constraints", {}).get("volume_fraction") is not None else None,
                    "grayRatio": float(result.get("quality", {}).get("gray_ratio")) if result.get("quality", {}).get("gray_ratio") is not None else None,
                    "durationSeconds": time.time() - started,
                })
                final_status = result.get("status")
                valid_terminal = final_status in {"completed", "converged", "max_iter", "timeout"}
                record.status = RunStatus.CANCELLED if final_status == "cancelled" or record.cancel_event.is_set() else (RunStatus.COMPLETED if valid_terminal else RunStatus.FAILED)
                if record.status is RunStatus.FAILED:
                    record.error = ErrorEnvelope(code="SOLVER_FAILED", source=ErrorSource.ENGINEERING, message=f"solver returned status {final_status}", retryable=True)
            self._emit(record, {"type": "status", "status": record.status.value})
        except MatlabInfrastructureError as exc:
            with record.lock:
                record.status = RunStatus.CANCELLED if record.cancel_event.is_set() else RunStatus.FAILED
                if record.status is RunStatus.FAILED:
                    source = ErrorSource.RUNTIME if record.lane is SolverLane.COMPILED_RUNTIME else ErrorSource.MATLAB
                    error_code = exc.code if record.lane is SolverLane.COMPILED_RUNTIME else "MATLAB_INFRASTRUCTURE"
                    record.error = ErrorEnvelope(code=error_code, source=source, message=str(exc)[:2000], retryable=True)
            self._index_artifacts(record)
            self._emit(record, {"type": "error", "status": record.status.value, "code": getattr(exc, "code", "MATLAB_INFRASTRUCTURE"), "message": str(exc)})
        except Exception as exc:
            with record.lock:
                record.status = RunStatus.CANCELLED if record.cancel_event.is_set() else RunStatus.FAILED
                if record.status is RunStatus.FAILED:
                    record.error = ErrorEnvelope(code="ENGINEERING_RUN_FAILED", source=ErrorSource.ENGINEERING, message=str(exc)[:2000], retryable=True)
            self._index_artifacts(record)
            self._emit(record, {"type": "error", "status": record.status.value, "message": str(exc)})

    def _run_external(self, record: _Run, time_limit: float | None, progress=None, console=None) -> dict[str, Any]:
        source_root = engineering_matlab_source_root()
        if record.lane is SolverLane.LOCAL_MATLAB:
            configured = os.environ.get("TOPOPTPILOT_MATLAB_PATH")
            installations = discover_matlab_installations(configured_path=configured, registry_roots=[], standard_roots=[], where_executables=[], path_value="") if configured else discover_matlab_installations()
            if not installations:
                raise MatlabInfrastructureError("未发现可验证的本机 MATLAB 安装")
            probe = asyncio.run(probe_matlab_installation(installations[0]))
            if not probe.usable:
                raise MatlabInfrastructureError(f"MATLAB 探针失败：{probe.diagnostic}")
            summary = run_matlab_batch(installations[0].executable, record.task, record.run_dir, source_root=source_root, cancel=record.cancel_event.is_set, timeout_seconds=time_limit, progress=progress, console=console)
        elif record.lane is SolverLane.COMPILED_RUNTIME:
            try:
                profile = runtime_profiles.resolve(record.runtime_profile_id or "")
            except (RuntimeProfileError, OSError) as exc:
                raise MatlabInfrastructureError(str(exc), code=getattr(exc, "code", "RUNTIME_PROFILE_STALE")) from exc
            staged_solver = stage_runtime_solver(profile, record.run_dir)
            command = build_runtime_command(staged_solver, record.run_dir / "config.json", record.run_dir)
            summary = run_runtime_solver(command, record.task, record.run_dir, runtime_root=profile.runtime_root, cancel=record.cancel_event.is_set, timeout_seconds=time_limit, progress=progress, console=console)
            provenance = summary.setdefault("provenance", {})
            if isinstance(provenance, dict):
                provenance["runtimeRelease"] = profile.runtime_release
                provenance["runtimeDllSha256"] = profile.runtime_identity.sha256
                provenance["solverSha256"] = profile.solver_identity.sha256
        else:
            raise MatlabInfrastructureError(f"科研 lane {record.lane.value} 不能从工程工作区启动")
        return normalize_external_summary(summary, record.lane)


manager = RunManager()
