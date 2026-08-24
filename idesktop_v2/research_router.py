"""Research artifact adapters and explicit engineering baseline linking."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from idesktop_v2.artifacts.models import RunStatus
from idesktop_v2.engineering.runs import manager
from idesktop_v2.research_artifacts import build_research_artifact_index
from topoptpilot.api.fastapi_app import service

router = APIRouter(prefix="/api/research", tags=["research-artifacts"])


class EngineeringBaselineRequest(BaseModel):
    name: str = Field(default="工程基线研究", min_length=1, max_length=120)
    goal: str = Field(default="以已验证工程运行为基线，经 Policy 审批后开展科研实验", min_length=1, max_length=2000)
    budgetTotal: int = Field(default=12, ge=1, le=10000)


@router.post("/from-engineering-run/{run_id}", status_code=201)
def research_from_engineering_run(run_id: str, request: EngineeringBaselineRequest) -> dict[str, object]:
    record = manager.get(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="engineering run not found")
    if record.status is not RunStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="only a completed engineering run can become a research baseline")
    artifact = record.public()
    baseline = {
        "runId": artifact["runId"],
        "lane": artifact["lane"],
        "configDigest": artifact["configDigest"],
        "metrics": artifact["metrics"],
        "provenance": artifact["provenance"],
    }
    research = service.create_research({
        "name": request.name,
        "goal": request.goal,
        "budget_total": request.budgetTotal,
        "mode": "COPILOT",
        "constraints": {"engineering_baseline": baseline},
    })
    service.store.append_event(
        research["id"],
        "BASELINE_LINKED",
        "已关联工程运行基线",
        f"工程 Run {run_id} 仅作为证据引用；任何科研实验仍须经过 Intent、Policy 与审批。",
        payload=baseline,
    )
    return service.get_research(research["id"])


@router.get("/{research_id}/artifacts")
def research_artifacts(research_id: str) -> dict[str, object]:
    try:
        research = service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_research_artifact_index(research, service.data_dir)


@router.get("/{research_id}/pareto")
def research_pareto(research_id: str) -> list[dict[str, object]]:
    try:
        return service.tools.research_get_pareto(research_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{research_id}/compare")
def research_compare(research_id: str, a: str = Query(min_length=1), b: str = Query(min_length=1)) -> dict[str, object]:
    try:
        return service.tools.experiment_compare(research_id, a, b)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
