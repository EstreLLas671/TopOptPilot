"""Competition/test API. Business behavior is delegated to ResearchService."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from topoptpilot.schemas import ExperimentCreate, ResearchCreate, ToolRequest
from topoptpilot.service import ResearchService


service = ResearchService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    service.close()


app = FastAPI(title="TopOptPilot Test API", version="5.0", lifespan=lifespan,
              description="Programmatic interface to the same ResearchService used by Streamlit.")


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


@app.get("/api/report/{research_id}")
def get_report(research_id: str):
    try:
        path = service.generate_report(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="text/markdown", filename=f"{research_id}_report.md")
