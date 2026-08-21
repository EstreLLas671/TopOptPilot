"""Competition/test API. Business behavior is delegated to ResearchService."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from topoptpilot.schemas import ExperimentCreate, ResearchCreate, ToolRequest
from topoptpilot.service import ResearchService


service = ResearchService()


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


class DecisionEditRequest(BaseModel):
    parameters: dict


class LocaleRequest(BaseModel):
    locale: str


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
def create_research(request: ResearchCreate):
    return service.create_research(request)


@app.get("/api/research")
def list_research():
    return service.list_research()


@app.post("/api/research/{research_id}/autonomous")
def start_autonomous(research_id: str):
    try:
        return service.start_autonomous_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/research/{research_id}/events")
def get_events(research_id: str, after: int = 0):
    service._require_research(research_id)
    return [item for item in service.store.list_events(research_id) if item["id"] > after]


@app.websocket("/api/research/{research_id}/stream")
async def stream_research(websocket: WebSocket, research_id: str):
    expected = os.environ.get("TOPPILOT_DESKTOP_TOKEN")
    if expected and websocket.query_params.get("token") != expected:
        await websocket.close(code=4401)
        return
    try:
        service._require_research(research_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    after, last_stream = 0, None
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
            await websocket.send_json({"type": "progress", "experiments": running})
            await asyncio.sleep(.5)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.post("/api/tools/invoke")
def invoke_tool(request: ToolRequest):
    try:
        return {"ok": True, "result": service.tools.invoke(request.research_id, request.tool,
                                                              request.arguments)}
    except (KeyError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/research/{research_id}")
def get_research(research_id: str):
    try:
        return service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/report/{research_id}")
def get_report(research_id: str):
    try:
        path = service.generate_report(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="text/markdown", filename=f"{research_id}_report.md")
