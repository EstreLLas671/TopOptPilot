"""工程求解任务、制品和进度流管理。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from idesktop_v2.artifacts.models import ArtifactRef, ErrorEnvelope, ErrorSource, OwnerType, RunArtifact, RunStatus, SolverLane
from idesktop_v2.engineering.artifact_index import discover_artifact_files, media_type_for
from idesktop_v2.engineering.external_summary import normalize_external_summary
from idesktop_v2.engineering.matlab import discover_matlab_installations, probe_matlab_installation
from idesktop_v2.engineering.matlab_runner import MatlabInfrastructureError, build_runtime_command, run_matlab_batch, run_runtime_solver
from idesktop_v2.engineering.runtime_profiles import RuntimeProfileError, runtime_profiles, stage_runtime_solver


def _data_root() -> Path:
    root = os.environ.get("IDESKTOP_V2_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "iDeskTopV2"
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
        threading.Thread(target=self._worker, args=(record, request.time_limit), daemon=True, name=f"idesktop-run-{run_id}").start()
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
            return self._runs.get(run_id)

    def cancel(self, run_id: str) -> _Run:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.cancel_event.set()
        with record.lock:
            if record.status is RunStatus.QUEUED:
                record.status = RunStatus.CANCELLED
        return record

    def events(self, run_id: str) -> list[dict[str, Any]]:
        record = self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        with record.lock:
            return list(record.events)

    def _emit(self, record: _Run, event: dict[str, Any]) -> None:
        with record.lock:
            record.events.append({"timestamp": time.time(), **event})

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

    def _worker(self, record: _Run, time_limit: float | None) -> None:
        with record.lock:
            if record.cancel_event.is_set():
                record.status = RunStatus.CANCELLED
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
                with record.lock:
                    record.metrics.update({
                        "iteration": float(iteration),
                        "iterations": float(iteration),
                        "compliance": float(state["compliance"]) if state.get("compliance") is not None else None,
                        "volumeFraction": float(state["volume_fraction"]) if state.get("volume_fraction") is not None else None,
                        "grayRatio": float(state["gray_ratio"]) if state.get("gray_ratio") is not None else None,
                    })
                self._emit(record, {"type": "progress", "iteration": iteration, "metrics": dict(record.metrics)})

            if record.lane is SolverLane.PYTHON_FEM:
                from solver.topopt_engine import run_topopt
                result = run_topopt(record.task, backend="python", time_limit=time_limit, progress=progress, cancel=record.cancel_event.is_set)
            else:
                result = self._run_external(record, time_limit)
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

    def _run_external(self, record: _Run, time_limit: float | None) -> dict[str, Any]:
        source_root = engineering_matlab_source_root()
        if record.lane is SolverLane.LOCAL_MATLAB:
            configured = os.environ.get("IDESKTOP_MATLAB_PATH")
            installations = discover_matlab_installations(configured_path=configured, registry_roots=[], standard_roots=[], where_executables=[], path_value="") if configured else discover_matlab_installations()
            if not installations:
                raise MatlabInfrastructureError("未发现可验证的本机 MATLAB 安装")
            probe = asyncio.run(probe_matlab_installation(installations[0], timeout_seconds=12.0))
            if not probe.usable:
                raise MatlabInfrastructureError(f"MATLAB 探针失败：{probe.diagnostic}")
            summary = run_matlab_batch(installations[0].executable, record.task, record.run_dir, source_root=source_root, cancel=record.cancel_event.is_set, timeout_seconds=time_limit)
        elif record.lane is SolverLane.COMPILED_RUNTIME:
            try:
                profile = runtime_profiles.resolve(record.runtime_profile_id or "")
            except (RuntimeProfileError, OSError) as exc:
                raise MatlabInfrastructureError(str(exc), code=getattr(exc, "code", "RUNTIME_PROFILE_STALE")) from exc
            staged_solver = stage_runtime_solver(profile, record.run_dir)
            command = build_runtime_command(staged_solver, record.run_dir / "config.json", record.run_dir)
            summary = run_runtime_solver(command, record.task, record.run_dir, runtime_root=profile.runtime_root, cancel=record.cancel_event.is_set, timeout_seconds=time_limit)
            provenance = summary.setdefault("provenance", {})
            if isinstance(provenance, dict):
                provenance["runtimeRelease"] = profile.runtime_release
                provenance["runtimeDllSha256"] = profile.runtime_identity.sha256
                provenance["solverSha256"] = profile.solver_identity.sha256
        else:
            raise MatlabInfrastructureError(f"科研 lane {record.lane.value} 不能从工程工作区启动")
        return normalize_external_summary(summary, record.lane)


manager = RunManager()
