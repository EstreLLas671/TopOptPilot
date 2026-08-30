"""Engineering API routes that never bypass the research policy lane."""

from __future__ import annotations

import asyncio
import os
import platform
import sys
from typing import Literal
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from topoptpilot_desktop import __version__
from topoptpilot_desktop.engineering.report import write_report
from topoptpilot_desktop.engineering.runs import RunCreateRequest, manager
from topoptpilot_desktop.engineering.comparison_schemes import comparison_schemes
from topoptpilot_desktop.engineering.terminal import MAX_COMMAND_BYTES, manager as terminal_manager
from topoptpilot_desktop.engineering.runtime_profiles import RuntimeProfileError, runtime_profiles
from topoptpilot_desktop.engineering.runtime_discovery import runtime_inventory
from topoptpilot_desktop.engineering.environment_discovery import matlab_inventory, discover_environment, invalidate_environment_cache
from topoptpilot_desktop.artifacts.models import RunStatus
from topoptpilot_desktop.engineering.matlab import (
    MatlabInstallation,
    classify_runtime_root,
    probe_matlab_installation,
)


router = APIRouter(prefix="/api/engineering", tags=["engineering"])
_solver_preference: Literal["local-matlab", "compiled-runtime"] = "local-matlab"


@router.get("/health")
def engineering_health() -> dict[str, object]:
    runtime_inventory.snapshot()
    matlab_inventory.snapshot()
    mode = "packaged" if getattr(sys, "frozen", False) else "source"
    return {
        "status": "ok", "service": "engineering", "version": __version__,
        "capabilities": {"localMatlab": "unprobed", "compiledRuntime": "optional"},
        "python": {"mode": mode, "version": platform.python_version(), "bundled": mode == "packaged"},
    }


@router.get("/environment")
async def engineering_environment() -> dict[str, object]:
    return await discover_environment()


@router.post("/environment/refresh")
async def engineering_environment_refresh() -> dict[str, object]:
    invalidate_environment_cache()
    return await discover_environment(force=True)


@router.get("/matlab/installations")
def matlab_installations(refresh: bool = False) -> dict[str, object]:
    installations = matlab_inventory.refresh() if refresh else matlab_inventory.snapshot()
    return {"preference": _solver_preference, "installations": [item.as_dict() for item in installations]}


class MatlabProbeRequest(BaseModel):
    executable: str = Field(min_length=1, max_length=500)
    release: str = ""


@router.post("/matlab/probe")
async def matlab_probe(request: MatlabProbeRequest) -> dict[str, object]:
    installation = MatlabInstallation(release=request.release, version="", executable=request.executable, source="settings")
    result = await probe_matlab_installation(installation)
    return result.as_dict()


class MatlabPreferenceRequest(BaseModel):
    preference: str


@router.post("/matlab/preference")
def matlab_preference(request: MatlabPreferenceRequest) -> dict[str, str]:
    global _solver_preference
    if request.preference not in {"local-matlab", "compiled-runtime"}:
        raise HTTPException(status_code=422, detail="engineering preference must be local-matlab or compiled-runtime")
    _solver_preference = request.preference  # type: ignore[assignment]
    return {"preference": _solver_preference}


class RuntimeProbeRequest(BaseModel):
    root: str = Field(min_length=1, max_length=500)
    solverExecutable: str = Field(min_length=1, max_length=1000)


@router.post("/runtime/probe")
def runtime_probe(request: RuntimeProbeRequest) -> dict[str, object]:
    try:
        return runtime_profiles.verify(request.root, request.solverExecutable).as_dict()
    except (RuntimeProfileError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runtime/bundled")
def bundled_runtime_probe() -> dict[str, object]:
    try:
        profile = runtime_profiles.verify_bundled_resource()
    except (RuntimeProfileError, OSError) as exc:
        code = exc.code if isinstance(exc, RuntimeProfileError) else "RUNTIME_BUNDLE_INVALID"
        raise HTTPException(
            status_code=422,
            detail={"code": code, "message": str(exc)},
        ) from exc
    if profile is None:
        return {
            "state": "unavailable", "usable": False, "profileId": None,
            "diagnostic": "当前为标准版，未捆绑 MATLAB Runtime",
        }
    return profile.as_dict()


@router.get("/runtime/installations")
def runtime_installations(refresh: bool = False) -> dict[str, object]:
    installations = runtime_inventory.refresh() if refresh else runtime_inventory.snapshot()
    payloads: list[dict[str, object]] = []
    for installation in installations:
        payload = installation.as_dict()
        payload.update({"runReady": False, "profileId": None, "solverExecutable": None})
        if installation.usable:
            try:
                profile = runtime_profiles.verify_compatible_installation(
                    installation.path,
                    installation.release,
                )
            except (RuntimeProfileError, OSError) as exc:
                payload["runReason"] = str(exc)
            else:
                payload.update({
                    "runReady": True,
                    "runReason": "Runtime 与同版本编译求解器已验证",
                    "profileId": profile.profile_id,
                    "solverExecutable": str(profile.solver_executable),
                })
        else:
            payload["runReason"] = installation.reason
        payloads.append(payload)
    return {
        "usable": any(item.usable for item in installations),
        "runReady": any(bool(item["runReady"]) for item in payloads),
        "installations": payloads,
    }

@router.post("/runs", status_code=202)
def engineering_run_create(request: RunCreateRequest) -> dict[str, object]:
    if request.lane.value == "compiled-runtime" and not request.runtime_profile_id:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "RUNTIME_PROFILE_REQUIRED",
                "message": "compiled-runtime API 请求必须携带已验证 runtimeProfileId",
            },
        )
    try:
        return manager.submit(request).public()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def engineering_run_list(project_id: str | None = Query(default=None, max_length=160), cursor: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)) -> dict[str, object]:
    records = manager.list(project_id)
    page = records[cursor:cursor + limit]
    next_cursor = cursor + len(page) if cursor + len(page) < len(records) else None
    return {"runs": [record.public() for record in page], "nextCursor": next_cursor}

def _record_or_404(run_id: str):
    record = manager.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="engineering run not found")
    return record


@router.get("/runs/{run_id}")
def engineering_run_get(run_id: str) -> dict[str, object]:
    return _record_or_404(run_id).public()


@router.post("/runs/{run_id}/cancel", status_code=202)
def engineering_run_cancel(run_id: str) -> dict[str, object]:
    try:
        return manager.cancel(run_id).public()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="engineering run not found") from exc


@router.get("/runs/{run_id}/artifacts")
def engineering_run_artifacts(run_id: str) -> dict[str, object]:
    return _record_or_404(run_id).public()


@router.get("/runs/{run_id}/snapshots")
def engineering_run_snapshots(run_id: str) -> dict[str, object]:
    record = _record_or_404(run_id)
    return {"runId": run_id, "snapshots": [item.model_dump(by_alias=True, mode="json") for item in record.snapshots]}


@router.get("/runs/{run_id}/files/{relative_path:path}")
def engineering_run_file(run_id: str, relative_path: str):
    record = _record_or_404(run_id)
    normalized = PurePosixPath(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    allowed = {item.relative_path for item in [*record.files, *record.snapshots]}
    if relative_path not in allowed:
        raise HTTPException(status_code=404, detail="artifact not found")
    target = (record.run_dir / Path(*normalized.parts)).resolve()
    if record.run_dir.resolve() not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target)

@router.get("/runs/{run_id}/events")
def engineering_run_events(run_id: str, after_seq: int = Query(default=0, ge=0)) -> dict[str, object]:
    try:
        events = manager.events(run_id)
        return {"runId": run_id, "events": [event for index, event in enumerate(events, 1) if int(event.get("seq", index)) > after_seq]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="engineering run not found") from exc


@router.get("/runs/{run_id}/console")
def engineering_run_console(run_id: str, after_seq: int = Query(default=0, ge=0)) -> dict[str, object]:
    try:
        events = manager.events(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="engineering run not found") from exc
    return {"runId": run_id, "events": [event for index, event in enumerate(events, 1) if event.get("type") == "console" and int(event.get("seq", index)) > after_seq]}

class EngineeringReportRequest(BaseModel):
    name: str = Field(default="report", min_length=1, max_length=120)
    outputDirectory: str | None = Field(default=None, max_length=1000)


@router.post("/runs/{run_id}/report")
def engineering_run_report(run_id: str, request: EngineeringReportRequest | None = None) -> dict[str, object]:
    request = request or EngineeringReportRequest()
    record = _record_or_404(run_id)
    if record.status not in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="run is not terminal")
    path = write_report(record, request.name)
    ref = manager._ref(record.run_dir, path, "text/markdown")
    if not any(item.relative_path == ref.relative_path for item in record.files):
        record.files.append(ref)
    manager.persist(record)
    response = ref.model_dump(by_alias=True, mode="json")
    if request.outputDirectory:
        output_directory = Path(request.outputDirectory).expanduser().resolve()
        if not output_directory.is_dir():
            raise HTTPException(status_code=422, detail="报告输出目录不存在")
        exported = output_directory / path.name
        exported.write_bytes(path.read_bytes())
        response["exportedPath"] = str(exported)
    return response


@router.websocket("/runs/{run_id}/stream")
async def engineering_run_stream(websocket: WebSocket, run_id: str) -> None:
    expected = os.environ.get("TOPPILOT_DESKTOP_TOKEN")
    if expected and websocket.query_params.get("token") != expected:
        await websocket.close(code=4401)
        return
    record = manager.get(run_id)
    if record is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    cursor = 0
    try:
        while True:
            with record.lock:
                pending = record.events[cursor:]
                cursor = len(record.events)
                terminal = record.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
            for event in pending:
                await websocket.send_json(event)
            if terminal and not pending:
                break
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        return
class ComparisonSchemeCreateRequest(BaseModel):
    run_id: str = Field(alias="runId", pattern=r"^eng-[0-9a-f]{32}$")
    name: str | None = Field(default=None, max_length=120)


@router.get("/comparison-schemes")
def comparison_scheme_list() -> list[dict[str, object]]:
    return comparison_schemes.list()


@router.post("/comparison-schemes", status_code=201)
def comparison_scheme_create(request: ComparisonSchemeCreateRequest) -> dict[str, object]:
    try:
        return comparison_schemes.create(request.run_id, request.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="engineering run not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/comparison-schemes/{scheme_id}")
def comparison_scheme_get(scheme_id: str) -> dict[str, object]:
    value = comparison_schemes.get(scheme_id)
    if value is None:
        raise HTTPException(status_code=404, detail="comparison scheme not found")
    return value


@router.delete("/comparison-schemes/{scheme_id}")
def comparison_scheme_delete(scheme_id: str) -> dict[str, object]:
    if not comparison_schemes.delete(scheme_id):
        raise HTTPException(status_code=404, detail="comparison scheme not found")
    return {"deleted": True, "id": scheme_id}



class TerminalStartRequest(BaseModel):
    project_root: str = Field(min_length=1, max_length=1000, alias="projectRoot")
    executable: str | None = Field(default=None, max_length=1000)
    bridge_script: str | None = Field(default=None, max_length=1000, alias="bridgeScript")


class TerminalCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=MAX_COMMAND_BYTES)


@router.post("/terminal/start", status_code=202)
def terminal_start(request: TerminalStartRequest) -> dict[str, object]:
    try:
        return terminal_manager.start(project_root=request.project_root, executable=request.executable, bridge_script=request.bridge_script)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/terminal/command", status_code=202)
def terminal_command(request: TerminalCommandRequest, session_id: str = "") -> dict[str, object]:
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        return terminal_manager.command(session_id, request.command)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MATLAB terminal session not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/terminal/{session_id}")
def terminal_poll(session_id: str) -> dict[str, object]:
    try:
        return terminal_manager.poll(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MATLAB terminal session not found") from exc


@router.post("/terminal/stop", status_code=202)
def terminal_stop(session_id: str = "") -> dict[str, object]:
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")
    try:
        return terminal_manager.stop(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="MATLAB terminal session not found") from exc
