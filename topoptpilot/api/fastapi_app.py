"""Competition/test API. Business behavior is delegated to ResearchService."""

from __future__ import annotations

import asyncio
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from topoptpilot.schemas import ExperimentCreate, ResearchCreate, ToolRequest
from topoptpilot.service import ResearchService
from mcp.matlab_mcp import MatlabMcpError


service = ResearchService()
_ws_tickets: dict[str, tuple[str, float]] = {}
_ws_ticket_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    service.close()


app = FastAPI(title="TopOptPilot Test API", version="5.0", lifespan=lifespan,
              description="Programmatic interface to the same ResearchService used by Streamlit.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"],
    allow_origin_regex=r"^https?://(tauri\.localhost|localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"], allow_headers=["*"], allow_credentials=False,
)


class CommandRequest(BaseModel):
    text: str = Field(min_length=1)
    selected_experiment: str | None = None


class FidelityStageDecisionRequest(BaseModel):
    advance: bool


class DecisionEditRequest(BaseModel):
    parameters: dict


class LocaleRequest(BaseModel):
    locale: str


class AgentKeyRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=2048)


class SettingsPatchRequest(BaseModel):
    settings: dict


class CacheClearRequest(BaseModel):
    confirm: bool = False


class ResearchReportExportRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    outputDirectory: str = Field(min_length=1, max_length=4096)
    formats: list[str] = Field(default_factory=lambda: ["markdown", "pdf"], min_length=1)
    overwrite: bool = False


class GuideRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    locale: str = "zh-CN"


class GeometryPreviewRequest(BaseModel):
    dimension: int = Field(ge=2, le=3)
    geometry: dict = Field(default_factory=dict)
    bc_type: str = Field(default="MBB", min_length=1, max_length=80)
    load_scale: float = Field(default=1.0, gt=0)
    grid: list[int]
    mask: list | None = None


@app.middleware("http")
async def desktop_token_guard(request: Request, call_next):
    expected = os.environ.get("TOPPILOT_DESKTOP_TOKEN")
    # Browser CORS preflights intentionally carry no application token. They
    # must reach CORSMiddleware; the subsequent real request is still guarded.
    if expected and request.method != "OPTIONS" and request.url.path != "/api/health":
        if request.headers.get("x-topoptpilot-token") != expected:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Invalid desktop session token"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return service.health()


@app.post("/api/research", status_code=201)
def create_research(request: dict):
    return service.create_research(request)


@app.get("/api/research")
def list_research(archived: bool = False):
    return service.list_research(archived=archived)


@app.delete("/api/research/{research_id}")
def archive_research(research_id: str, confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="归档前必须显式确认")
    try:
        return service.archive_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/restore")
def restore_research(research_id: str):
    try:
        return service.restore_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/autonomous")
def start_autonomous(research_id: str):
    try:
        return service.start_autonomous_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/autonomous/stop")
def stop_autonomous(research_id: str):
    try:
        return service.stop_autonomous_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/research/{research_id}/runs")
def list_research_runs(research_id: str):
    service._require_research(research_id)
    return service.store.list_research_runs(research_id)


@app.post("/api/research/{research_id}/fidelity-stage-decision")
def decide_fidelity_stage(research_id: str, request: FidelityStageDecisionRequest):
    try:
        return service.decide_fidelity_stage(research_id, request.advance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/research/{research_id}/events")
def get_events(research_id: str, after: int = 0):
    service._require_research(research_id)
    return [item for item in service.store.list_events(research_id) if item["id"] > after]


@app.post("/api/research/{research_id}/stream-ticket")
def create_stream_ticket(research_id: str):
    service._require_research(research_id)
    ticket = secrets.token_urlsafe(32)
    with _ws_ticket_lock:
        now = time.monotonic()
        for key, (_, expires) in list(_ws_tickets.items()):
            if expires <= now:
                _ws_tickets.pop(key, None)
        _ws_tickets[ticket] = (research_id, now + 20.0)
    return {"ticket": ticket, "expires_in": 20}


@app.websocket("/api/research/{research_id}/stream")
async def stream_research(websocket: WebSocket, research_id: str):
    ticket = websocket.query_params.get("ticket", "")
    with _ws_ticket_lock:
        record = _ws_tickets.pop(ticket, None)
    if not record or record[0] != research_id or record[1] <= time.monotonic():
        await websocket.close(code=4401)
        return
    try:
        service._require_research(research_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    after, last_stream, last_workflow = 0, None, None
    try:
        while True:
            events = [item for item in service.store.list_events(research_id)
                      if item["id"] > after]
            if events:
                after = events[-1]["id"]
                await websocket.send_json({"type": "events", "events": events})
            session = service.store.get_agent_session(research_id) or {}
            current_stream = (session.get("status"), session.get("stream_text"),
                              session.get("context_usage"), session.get("last_error"))
            if current_stream != last_stream:
                last_stream = current_stream
                await websocket.send_json({"type": "agent_session", "session": session})
            experiments = service.store.list_experiments(research_id)
            running = [item for item in experiments if item["status"] in {"WAITING", "RUNNING"}]
            if running:
                await websocket.send_json({"type": "progress", "experiments": running})
            workflow = service.get_research(research_id).get("workflow")
            if workflow != last_workflow:
                last_workflow = workflow
                await websocket.send_json({"type": "workflow_progress", "workflow": workflow})
            await asyncio.sleep(.5)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.post("/api/tools/invoke")
def invoke_tool(request: ToolRequest):
    try:
        return {"ok": True, "result": service.tools.invoke(request.research_id, request.tool,
                                                              request.arguments, source=request.source)}
    except (KeyError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research/{research_id}")
def get_research(research_id: str):
    try:
        return service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/research/{research_id}/compare")
def compare_experiments(research_id: str, a: str, b: str):
    try:
        return service.tools.experiment_compare(research_id, a, b)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/guide")
def guide_research(research_id: str, request: GuideRequest):
    try:
        return service.guide_research(research_id, request.text)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/guide")
def preview_guide(request: GuideRequest):
    if request.locale not in {"zh-CN", "en-US"}:
        raise HTTPException(status_code=422, detail="locale must be zh-CN or en-US")
    return service.preview_guidance(request.text, request.locale)


@app.post("/api/research/guide/parse")
def parse_guided_setup(request: GuideRequest):
    """V6.1 documented alias for the guided-setup parse step."""
    if request.locale not in {"zh-CN", "en-US"}:
        raise HTTPException(status_code=422, detail="locale must be zh-CN or en-US")
    return service.preview_guidance(request.text, request.locale)


@app.get("/api/research/{research_id}/agent-tasks")
def list_agent_tasks(research_id: str):
    service._require_research(research_id)
    return service.store.list_subagent_tasks(research_id)


@app.get("/api/knowledge/search")
def search_knowledge(q: str = "", locale: str = "zh-CN", category: str | None = None,
                     limit: int = 8):
    if locale not in {"zh-CN", "en-US"}:
        raise HTTPException(status_code=422, detail="locale must be zh-CN or en-US")
    return {"items": service.knowledge.search(q, locale, category, limit),
            "categories": service.knowledge.categories(locale)}


@app.get("/api/knowledge/{document_id}")
def get_knowledge(document_id: str, locale: str = "zh-CN"):
    try:
        return service.knowledge.get(document_id, locale)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/solvers/capabilities")
def solver_capabilities():
    return service.solver_capabilities()


@app.post("/api/solvers/geometry-preview")
def geometry_preview(request: GeometryPreviewRequest):
    try:
        return service.preview_geometry(request.model_dump())
    except (ValueError, MatlabMcpError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/research/{research_id}/commands")
def execute_command(research_id: str, request: CommandRequest):
    try:
        return service.execute_command(research_id, request.text, request.selected_experiment)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/research/{research_id}/locale")
def set_locale(research_id: str, request: LocaleRequest):
    if request.locale not in {"zh-CN", "en-US"}:
        raise HTTPException(status_code=422, detail="locale must be zh-CN or en-US")
    service._require_research(research_id)
    return service.store.update_research(research_id, locale=request.locale)


@app.post("/api/research/{research_id}/experiments", status_code=201)
def create_experiment(research_id: str, request: ExperimentCreate):
    try:
        return service.create_experiment(research_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/experiments", status_code=201)
def create_experiment_compat(research_id: str, request: ExperimentCreate):
    return create_experiment(research_id, request)


@app.get("/api/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    try:
        return service.get_experiment(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/decision/{decision_id}/approve")
def approve_decision(decision_id: str):
    try:
        return service.approve_decision(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/decision/{decision_id}/reject")
def reject_decision(decision_id: str):
    try:
        return service.reject_decision(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/decision/{decision_id}/edit")
def edit_decision(decision_id: str, request: DecisionEditRequest):
    try:
        decision = service._require_decision(decision_id)
        if not decision.get("experiment_id"):
            raise ValueError("Decision has no experiment")
        return service.edit_pending_experiment(decision["experiment_id"], request.parameters)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/decision/{decision_id}/why")
def decision_reason(decision_id: str):
    try:
        decision = service._require_decision(decision_id)
        return {"id": decision_id, "reason": decision["reason"], "risk": decision["risk"],
                "proposal": decision["proposal"]}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/matlab/health")
def matlab_health():
    return service.matlab_health()


@app.post("/api/matlab/restart")
def matlab_restart():
    try:
        return service.restart_matlab()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/settings")
def get_settings():
    return service.get_settings()


@app.patch("/api/settings")
def patch_settings(request: SettingsPatchRequest):
    try:
        return service.update_settings(request.settings)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/settings/test-agent")
def test_agent_settings():
    return service.test_agent_settings()


@app.post("/api/settings/agent-key")
def set_agent_key(request: AgentKeyRequest):
    try:
        return service.set_agent_key(request.api_key)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/settings/agent-key")
def delete_agent_key():
    try:
        return service.delete_agent_key()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/settings/agent-credential")
def set_agent_credential(request: AgentKeyRequest):
    """V6.1 documented endpoint name; identical behaviour to agent-key."""
    try:
        return service.set_agent_key(request.api_key)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/settings/agent-credential")
def delete_agent_credential():
    """V6.1 documented endpoint name; identical behaviour to agent-key."""
    try:
        return service.delete_agent_key()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

@app.post("/api/settings/restart-pi")
def restart_pi_settings():
    try:
        return service.restart_pi()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/settings/restart-matlab")
def restart_matlab_settings():
    try:
        return service.restart_matlab()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/settings/diagnostics")
def settings_diagnostics():
    return service.diagnostics()


@app.post("/api/settings/export-diagnostics")
def export_diagnostics():
    path = service.export_diagnostics()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/settings/clear-cache")
def clear_cache(request: CacheClearRequest):
    if not request.confirm:
        raise HTTPException(status_code=400, detail="Confirmation is required; research and MATLAB evidence are retained.")
    return service.clear_regenerable_cache()


@app.get("/api/report/{research_id}")
def get_report(research_id: str):
    try:
        path = service.generate_report(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="text/markdown", filename=f"{research_id}_report.md")


@app.get("/api/report/{research_id}/pdf")
def get_report_pdf(research_id: str):
    try:
        path = service.report_path(research_id, "pdf")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/pdf", filename=f"{research_id}_report.pdf")


@app.post("/api/research/{research_id}/reports/export")
def export_research_report(research_id: str, request: ResearchReportExportRequest):
    try:
        return service.export_report(
            research_id, name=request.name, output_directory=request.outputDirectory,
            formats=request.formats, overwrite=request.overwrite,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
