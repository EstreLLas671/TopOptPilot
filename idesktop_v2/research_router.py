"""Research artifact adapters and explicit engineering baseline linking."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from idesktop_v2.artifacts.models import RunStatus
from idesktop_v2.assistant.router import _model_chat
from idesktop_v2.engineering.runs import manager
from idesktop_v2.research_artifacts import build_research_artifact_index
from topoptpilot.api.fastapi_app import service

router = APIRouter(prefix="/api/research", tags=["research-artifacts"])
settings_router = APIRouter(tags=["research-settings"])


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


class ResearchMaterialConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: Literal["normalized", "structural-steel", "aluminum-6061-t6", "titanium-ti6al4v", "custom"] = "normalized"
    name: str = Field(default="归一化参考材料", min_length=1, max_length=80)
    youngsModulusGPa: float = Field(default=1, gt=0)
    poissonRatio: float = Field(default=0.3, gt=-1, lt=0.5)
    densityKgM3: float = Field(default=1, gt=0)
    yieldStrengthMPa: float = Field(default=1, gt=0)


class ResearchOptimizationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1)
    dimension: Literal["2d", "3d"] = "3d"
    bcType: Literal["cantilever", "MBB", "simply_supported", "L-bracket"] = "cantilever"
    accuracy: Literal["standard", "high"] = "standard"
    nelx: int = Field(default=24, ge=1, le=2000)
    nely: int = Field(default=8, ge=1, le=2000)
    nelz: int = Field(default=6, ge=1, le=2000)
    volfrac: float = Field(default=0.4, gt=0, le=1)
    penal: float = Field(default=3, ge=1, le=5)
    rmin: float = Field(default=1.5, gt=0)
    maxIterations: int = Field(default=60, ge=1, le=2000)
    minIterations: int = Field(default=10, ge=1, le=2000)
    filterStrategy: Literal["fixed", "adaptive"] = "fixed"
    material: ResearchMaterialConfig = Field(default_factory=ResearchMaterialConfig)

    @model_validator(mode="after")
    def validate_iterations(self):
        if self.minIterations > self.maxIterations:
            raise ValueError("minIterations must not exceed maxIterations")
        return self


class ResearchGoalRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)


class ResearchHypothesisRequest(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=4000)


class ResearchStateActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["apply_research_state"] = "apply_research_state"
    goal: str | None = Field(default=None, min_length=1, max_length=2000)
    hypothesis: str | None = Field(default=None, min_length=1, max_length=4000)
    optimizationConfig: ResearchOptimizationConfig | None = None
    changedFields: list[Literal["goal", "hypothesis", "optimizationConfig"]] = Field(min_length=1, max_length=3)
    rationale: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_changed_fields(self):
        unique = list(dict.fromkeys(self.changedFields))
        if len(unique) != len(self.changedFields):
            raise ValueError("changedFields must not contain duplicates")
        for field in unique:
            if getattr(self, field) is None:
                raise ValueError(f"{field} must be present when listed in changedFields")
        return self


class ResearchVisionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    attachmentIds: list[str] = Field(min_length=1, max_length=4)


class ResearchChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    selectedExperiment: str | None = Field(default=None, max_length=160)


def _research_config(research_id: str) -> ResearchOptimizationConfig:
    research = service.get_research(research_id)
    defaults = dict(research.get("defaults") or {})
    raw = defaults.get("optimization_config")
    if raw:
        return ResearchOptimizationConfig.model_validate(raw)
    geometry = research.get("geometry") or {}
    material = research.get("material") or {}
    raw_dimension = str(geometry.get("dimension") or "3d").lower()
    seed = ResearchOptimizationConfig(
        dimension="2d" if raw_dimension in {"2", "2d"} else "3d",
        material=ResearchMaterialConfig(
            preset="normalized",
            name=str(material.get("name") or "归一化参考材料"),
            youngsModulusGPa=float(material.get("E") or material.get("youngs_modulus_gpa") or 1),
            poissonRatio=float(material.get("nu") or material.get("poisson_ratio") or 0.3),
            densityKgM3=float(material.get("density_kg_m3") or 1),
            yieldStrengthMPa=float(material.get("yield_strength_mpa") or 1),
        ),
    )
    defaults["optimization_config"] = seed.model_dump()
    service.store.update_research_json(research_id, defaults=defaults)
    service.store.append_event(
        research_id, "CONFIG_INITIALIZED", "科研默认参数已初始化",
        "已从 Research 契约或产品默认值生成版本化优化配置；既有实验记录未被改写。",
        payload={"config": seed.model_dump()},
    )
    return seed


@router.get("/{research_id}/optimization-config", response_model=ResearchOptimizationConfig)
@settings_router.get("/api/researches/{research_id}/optimization-config", response_model=ResearchOptimizationConfig)
def get_research_optimization_config(research_id: str) -> ResearchOptimizationConfig:
    try:
        return _research_config(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{research_id}/optimization-config", response_model=ResearchOptimizationConfig)
@settings_router.put("/api/researches/{research_id}/optimization-config", response_model=ResearchOptimizationConfig)
def put_research_optimization_config(research_id: str, request: ResearchOptimizationConfig) -> ResearchOptimizationConfig:
    try:
        research = service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    defaults = dict(research.get("defaults") or {})
    payload = request.model_dump()
    defaults["optimization_config"] = payload
    service.store.update_research_json(research_id, defaults=defaults)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    service.store.append_event(
        research_id, "CONFIG_UPDATED", "科研默认参数已更新",
        "后续实验提案将以该配置为默认值，单次覆写仍需通过 Policy 与审批。",
        payload={"config_digest": digest},
    )
    return request


@router.put("/{research_id}/goal")
@settings_router.put("/api/researches/{research_id}/goal")
def put_research_goal(research_id: str, request: ResearchGoalRequest) -> dict[str, object]:
    try:
        previous = service.get_research(research_id).get("goal", "")
        updated = service.store.update_research(research_id, goal=request.goal.strip())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service.store.append_event(
        research_id, "GOAL_UPDATED", "研究目标已更新",
        "研究者修改了 Research 目标；变更已进入审计记录。",
        payload={"previous": previous, "current": request.goal.strip()},
    )
    return updated


@router.put("/{research_id}/hypothesis")
@settings_router.put("/api/researches/{research_id}/hypothesis")
def put_research_hypothesis(research_id: str, request: ResearchHypothesisRequest) -> dict[str, object]:
    statement = request.hypothesis.strip()
    try:
        current = service.get_research(research_id)
        previous = current.get("hypothesis") or ""
        updated = service.store.update_research(research_id, hypothesis=statement)
        service.store.create_hypothesis({
            "id": "hyp-" + uuid.uuid4().hex,
            "research_id": research_id,
            "round_number": max(1, int(current.get("current_round") or 0) + 1),
            "statement": statement,
            "source": "USER",
            "status": "ACTIVE",
        })
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service.store.append_event(
        research_id, "HYPOTHESIS_UPDATED", "研究假设已更新",
        "研究者更新了当前假设；历史版本已保留。",
        payload={"previous": previous, "current": statement},
    )
    return service.get_research(updated["id"])


@settings_router.post("/api/researches/{research_id}/apply-suggestion")
def apply_research_suggestion(research_id: str, request: ResearchStateActionRequest) -> dict[str, object]:
    try:
        current = service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload: dict[str, object] = {"changed_fields": request.changedFields}
    if "goal" in request.changedFields and request.goal is not None:
        service.store.update_research(research_id, goal=request.goal.strip())
    if "hypothesis" in request.changedFields and request.hypothesis is not None:
        statement = request.hypothesis.strip()
        service.store.update_research(research_id, hypothesis=statement)
        service.store.create_hypothesis({
            "id": "hyp-" + uuid.uuid4().hex,
            "research_id": research_id,
            "round_number": max(1, int(current.get("current_round") or 0) + 1),
            "statement": statement,
            "source": "AGENT_APPROVED",
            "status": "ACTIVE",
        })
    saved_config = None
    if "optimizationConfig" in request.changedFields and request.optimizationConfig is not None:
        defaults = dict(current.get("defaults") or {})
        config_payload = request.optimizationConfig.model_dump()
        defaults["optimization_config"] = config_payload
        service.store.update_research_json(research_id, defaults=defaults)
        payload["config_digest"] = hashlib.sha256(
            json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        saved_config = config_payload
    service.store.append_event(
        research_id, "AGENT_SUGGESTION_APPROVED", "已批准并填入 Agent 建议",
        request.rationale or "研究者确认了目标、假设或参数变更；未自动启动实验。",
        payload=payload,
    )
    return {"research": service.get_research(research_id), "optimizationConfig": saved_config}


def _research_action(content: str) -> tuple[str, list[dict[str, object]]]:
    match = re.search(
        r"<topoptpilot-research-action>\s*([\s\S]*?)\s*</topoptpilot-research-action>",
        content,
        re.IGNORECASE,
    )
    action = None
    if match:
        try:
            action = ResearchStateActionRequest.model_validate(json.loads(match.group(1)))
        except (ValueError, TypeError, json.JSONDecodeError):
            action = None
    reply = re.sub(
        r"<topoptpilot-research-action>\s*[\s\S]*?\s*</topoptpilot-research-action>",
        "",
        content,
        flags=re.IGNORECASE,
    ).strip()
    return reply, [action.model_dump(exclude_none=True)] if action else []


@router.post("/{research_id}/vision-chat")
def research_vision_chat(research_id: str, request: ResearchVisionRequest) -> dict[str, object]:
    try:
        context = service.tools.research_get_context(research_id)
        response = _model_chat([
            {
                "role": "system",
                "content": (
                    "你是 TopOptPilot 的科研图像分析助手。仅基于提供的 Research State 与图片回答，"
                    "区分观察与假设，不得绕过 Policy、预算或 F0-F3 审批，不得直接启动实验。"
                    "若研究目标或假设为空，应明确指出并给出可编辑建议；仅在用户要求填入时，可在回复末尾附加"
                    "<topoptpilot-research-action>{\"type\":\"apply_research_state\",\"goal\":\"可选\","
                    "\"hypothesis\":\"可选\",\"optimizationConfig\":完整合法配置,\"changedFields\":[实际字段],"
                    "\"rationale\":\"简短原因\"}</topoptpilot-research-action>。"
                ),
            },
            {
                "role": "user",
                "content": "科研问题：" + request.message + chr(10) + "Research State：" + json.dumps(context, ensure_ascii=False, default=str),
                "attachmentIds": request.attachmentIds,
            },
        ])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    digest = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    if not response.get("success"):
        source = "not_configured" if response.get("error") == "not_configured" else "safe_mode"
        return {"reply": "", "source": source, "contextDigest": digest}
    reply, actions = _research_action(str(response.get("content") or ""))
    return {"reply": reply, "source": "qwen", "contextDigest": digest, "actions": actions}

@router.post("/{research_id}/chat")
def research_chat(research_id: str, request: ResearchChatRequest) -> dict[str, object]:
    """Answer a read-only Research question without persisting chat text in SQLite."""
    try:
        context = service.tools.research_get_context(research_id)
        selected = None
        if request.selectedExperiment:
            candidate = service.store.get_experiment(request.selectedExperiment)
            if candidate and candidate.get("research_id") == research_id:
                selected = {
                    "id": candidate.get("id"),
                    "status": candidate.get("status"),
                    "parameters": candidate.get("parameters"),
                    "result": candidate.get("result"),
                }
        evidence = {"research": context, "selected_experiment": selected}
        response = _model_chat([
            {
                "role": "system",
                "content": (
                    "你是 TopOptPilot 的科研对话助手。仅基于提供的 Research State 回答，"
                    "区分事实、观察与假设；不得伪造实验结果，不得绕过 Policy、预算或 F0-F3 审批，"
                    "也不得直接启动实验。用户要求执行时，应说明需要进入受控自主研究或审批流程。"
                    "若研究目标或假设为空，必须明确提示缺失项并给出推荐内容。只有用户要求填入或修改时，"
                    "才可在回复末尾附加 <topoptpilot-research-action>{\"type\":\"apply_research_state\","
                    "\"goal\":\"可选\",\"hypothesis\":\"可选\",\"optimizationConfig\":完整合法配置,"
                    "\"changedFields\":[实际字段],\"rationale\":\"简短原因\"}</topoptpilot-research-action>；"
                    "动作不得包含命令、文件路径、代码或自动运行字段。"
                ),
            },
            {
                "role": "user",
                "content": "科研问题：" + request.message + chr(10) + "Research State：" + json.dumps(evidence, ensure_ascii=False, default=str),
            },
        ])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    if not response.get("success"):
        source = "not_configured" if response.get("error") == "not_configured" else "safe_mode"
        return {"reply": "", "source": source, "contextDigest": digest}
    reply, actions = _research_action(str(response.get("content") or ""))
    return {"reply": reply, "source": "qwen", "contextDigest": digest, "actions": actions}
