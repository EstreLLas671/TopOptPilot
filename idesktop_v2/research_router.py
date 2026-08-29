"""Research artifact adapters and explicit engineering baseline linking."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from idesktop_v2.artifacts.models import RunStatus
from idesktop_v2.assistant.router import _model_chat
from idesktop_v2.engineering.comparison_schemes import comparison_schemes
from idesktop_v2.engineering.runs import manager
from idesktop_v2.research_artifacts import build_research_artifact_index
from topoptpilot.api.fastapi_app import service

router = APIRouter(prefix="/api/research", tags=["research-artifacts"])
settings_router = APIRouter(tags=["research-settings"])


class EngineeringBaselineRequest(BaseModel):
    name: str = Field(default="工程基线研究", min_length=1, max_length=120)
    goal: str = Field(default="以已验证工程运行为基线，经 Policy 审批后开展科研实验", min_length=1, max_length=2000)
    budgetTotal: int = Field(default=12, ge=1, le=10000)


class EngineeringSchemeImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemeId: str = Field(min_length=1, max_length=160)


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


def _research_config_from_engineering_task(task: dict[str, object]) -> ResearchOptimizationConfig:
    geometry = dict(task.get("geometry") or {})
    params = dict(task.get("params") or {})
    material = dict(task.get("material") or {})
    load_case = str(task.get("load_case") or "cantilever")
    if load_case.lower() in {"mbb", "vertical"}:
        load_case = "MBB"
    elif load_case.lower() == "lateral":
        load_case = "cantilever"
    return ResearchOptimizationConfig(
        dimension=str(task.get("dimension") or "3d").lower(),
        bcType=load_case,
        accuracy=str(params.get("accuracy") or "standard"),
        nelx=int(geometry.get("nelx") or 24),
        nely=int(geometry.get("nely") or 8),
        nelz=int(geometry.get("nelz") or 1),
        volfrac=float(params.get("volfrac") or 0.4),
        penal=float(params.get("penal") or 3),
        rmin=float(params.get("rmin") or 1.5),
        maxIterations=int(params.get("max_iter") or 60),
        minIterations=int(params.get("min_iter") or 10),
        filterStrategy=str(params.get("filter_strategy") or "fixed"),
        material=ResearchMaterialConfig(
            preset=str(material.get("preset") or "normalized"),
            name=str(material.get("name") or "归一化参考材料"),
            youngsModulusGPa=float(material.get("E_GPa") or material.get("E") or params.get("E") or 1),
            poissonRatio=float(material.get("nu") if material.get("nu") is not None else params.get("nu") or 0.3),
            densityKgM3=float(material.get("density_kg_m3") or 1),
            yieldStrengthMPa=float(material.get("yield_strength_MPa") or 1),
        ),
    )


@router.post("/{research_id}/engineering-baselines")
def import_engineering_scheme(research_id: str, request: EngineeringSchemeImportRequest) -> dict[str, object]:
    try:
        research = service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scheme = comparison_schemes.get(request.schemeId)
    if scheme is None:
        raise HTTPException(status_code=404, detail="engineering comparison scheme not found")
    run = scheme.get("run")
    if scheme.get("integrity") != "verified" or not isinstance(run, dict):
        raise HTTPException(status_code=409, detail="engineering scheme integrity is not verified")
    if run.get("status") != "completed":
        raise HTTPException(status_code=409, detail="only a completed engineering scheme can be imported")
    provenance = dict(run.get("provenance") or {})
    if provenance.get("resultKind") != "solver" or not run.get("files"):
        raise HTTPException(status_code=409, detail="engineering scheme lacks real solver evidence")
    if run.get("configDigest") != scheme.get("configDigest"):
        raise HTTPException(status_code=409, detail="engineering scheme config digest mismatch")
    try:
        config = _research_config_from_engineering_task(dict(scheme.get("config") or {}))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"engineering scheme configuration is incompatible: {exc}") from exc
    baseline = {
        "schemeId": scheme["id"],
        "name": scheme["name"],
        "runId": scheme["runId"],
        "configDigest": scheme["configDigest"],
        "metrics": dict(run.get("metrics") or {}),
        "provenance": provenance,
        "importedFrom": "engineering-comparison-scheme",
    }
    defaults = dict(research.get("defaults") or {})
    defaults["optimization_config"] = config.model_dump()
    defaults["engineering_scheme_baseline"] = baseline
    service.store.update_research_json(research_id, defaults=defaults)
    service.store.append_event(
        research_id,
        "ENGINEERING_BASELINE_IMPORTED",
        "已导入工程方案基线",
        f"方案“{scheme['name']}”已作为真实证据和参数草稿导入；尚未启动科研实验。",
        payload=baseline,
    )
    return {
        "research": service.get_research(research_id),
        "optimizationConfig": config.model_dump(),
        "baseline": baseline,
    }


@router.get("/{research_id}/artifacts")
def research_artifacts(research_id: str) -> dict[str, object]:
    try:
        research = service.get_research(research_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return build_research_artifact_index(research, service.data_dir)


def _research_visualization(research_id: str, experiment_id: str):
    import numpy as np
    experiment = service.store.get_experiment(experiment_id)
    if not experiment or experiment.get("research_id") != research_id:
        raise HTTPException(status_code=404, detail="research experiment not found")
    result = experiment.get("result") or {}
    root = (service.data_dir / research_id / "artifacts" / experiment_id).resolve()
    density_path = (root / "density.npy").resolve()
    if root not in density_path.parents or not density_path.is_file():
        raise HTTPException(status_code=404, detail="real density visualization is unavailable")
    try:
        density = np.load(density_path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="real density visualization is unreadable") from exc
    if density.ndim not in {2, 3} or density.size == 0 or not np.isfinite(density).all():
        raise HTTPException(status_code=422, detail="real density visualization has an invalid shape")
    stress_path = (root / "stress.npy").resolve()
    stress = None
    if stress_path.is_file():
        try:
            candidate = np.load(stress_path, allow_pickle=False)
        except (OSError, ValueError):
            candidate = None
        if candidate is not None and candidate.shape == density.shape and np.isfinite(candidate).all():
            stress = candidate
    shape = [int(value) for value in density.shape]
    if density.ndim == 2:
        shape.append(1)
    artifacts = result.get("artifacts") or {}
    return experiment, result, artifacts, density, stress, shape


@router.get("/{research_id}/experiments/{experiment_id}/visualization")
def research_visualization_manifest(research_id: str, experiment_id: str) -> dict[str, object]:
    experiment, result, artifacts, density, stress, shape = _research_visualization(research_id, experiment_id)
    return {
        "researchId": research_id,
        "experimentId": experiment_id,
        "dimension": "3d" if density.ndim == 3 and density.shape[2] > 1 else "2d",
        "shape": shape,
        "encoding": "float32-le",
        "order": "F",
        "hasStress": stress is not None,
        "history": list(artifacts.get("history") or []),
        "metrics": {
            "compliance": result.get("objective", {}).get("compliance"),
            "volumeFraction": result.get("constraints", {}).get("volume_fraction"),
            "grayRatio": result.get("quality", {}).get("gray_ratio"),
            "connectedComponents": result.get("quality", {}).get("connected_components"),
        },
        "config": dict(experiment.get("parameters") or {}),
        "backend": experiment.get("backend"),
        "fidelity": experiment.get("fidelity"),
        "status": experiment.get("status"),
        "evidenceIds": list(experiment.get("evidence_ids") or []) + list(artifacts.get("lineage_ids") or []),
        "resultSource": experiment.get("result_source"),
    }


@router.get("/{research_id}/experiments/{experiment_id}/visualization/density")
def research_visualization_density(research_id: str, experiment_id: str) -> Response:
    import numpy as np
    _, _, _, density, _, _ = _research_visualization(research_id, experiment_id)
    payload = np.asarray(density, dtype="<f4").tobytes(order="F")
    return Response(content=payload, media_type="application/octet-stream")


@router.get("/{research_id}/experiments/{experiment_id}/visualization/stress")
def research_visualization_stress(research_id: str, experiment_id: str) -> Response:
    import numpy as np
    _, _, _, _, stress, _ = _research_visualization(research_id, experiment_id)
    if stress is None:
        raise HTTPException(status_code=404, detail="real stress visualization is unavailable")
    return Response(content=np.asarray(stress, dtype="<f4").tobytes(order="F"), media_type="application/octet-stream")


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


def _research_config_template(research_id: str) -> tuple[ResearchOptimizationConfig, bool]:
    research = service.get_research(research_id)
    defaults = dict(research.get("defaults") or {})
    raw = defaults.get("optimization_config")
    if raw:
        return ResearchOptimizationConfig.model_validate(raw), True
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
    return seed, False


def _research_config(research_id: str) -> ResearchOptimizationConfig:
    seed, persisted = _research_config_template(research_id)
    if persisted:
        return seed
    research = service.get_research(research_id)
    defaults = dict(research.get("defaults") or {})
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


def _research_state_missing(context: dict[str, object]) -> bool:
    research = context.get("research") if isinstance(context.get("research"), dict) else context
    return not str(research.get("goal") or "").strip() or not str(research.get("hypothesis") or "").strip()


def _complete_missing_state_action(action: dict[str, object]) -> bool:
    try:
        parsed = ResearchStateActionRequest.model_validate(action)
    except (ValueError, TypeError):
        return False
    return set(parsed.changedFields) == {"goal", "hypothesis", "optimizationConfig"}


def _retry_missing_state_action(
    research_id: str,
    context: dict[str, object],
    reply: str,
    actions: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Retry once with the configured default model when a missing-state suggestion lacks a safe action."""
    if not _research_state_missing(context):
        return actions
    valid = [action for action in actions if _complete_missing_state_action(action)]
    if valid:
        return valid[:1]
    config = _research_config_template(research_id)[0].model_dump()
    extraction = _model_chat([
        {
            "role": "system",
            "content": (
                "你是 TopOptPilot 的受限研究状态提取器。只输出一个 "
                "<topoptpilot-research-action>JSON</topoptpilot-research-action>，不得输出其他文字。"
                "JSON 必须是 apply_research_state，且同时包含非空 goal、非空 hypothesis、完整合法 "
                "optimizationConfig，并令 changedFields 严格等于 "
                "[\"goal\",\"hypothesis\",\"optimizationConfig\"]。"
                "不得包含命令、路径、代码、自动运行或未声明字段。"
            ),
        },
        {
            "role": "user",
            "content": (
                "当前 Research State：" + json.dumps(context, ensure_ascii=False, default=str)
                + chr(10) + "当前合法参数模板：" + json.dumps(config, ensure_ascii=False)
                + chr(10) + "首次回复：" + reply
            ),
        },
    ])
    if not extraction.get("success"):
        return []
    _, extracted = _research_action(str(extraction.get("content") or ""))
    return [action for action in extracted if _complete_missing_state_action(action)][:1]


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
                    "若研究目标或假设为空，应明确指出并给出可编辑建议，同时必须在回复末尾附加"
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
    actions = _retry_missing_state_action(research_id, context, reply, actions)
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
                    "若研究目标或假设为空，必须明确提示缺失项并给出推荐内容，同时必须在回复末尾附加 "
                    "<topoptpilot-research-action>{\"type\":\"apply_research_state\","
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
    actions = _retry_missing_state_action(research_id, context, reply, actions)
    return {"reply": reply, "source": "qwen", "contextDigest": digest, "actions": actions}
