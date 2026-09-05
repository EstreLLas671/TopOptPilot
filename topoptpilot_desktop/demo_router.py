"""Desktop demonstration state backed exclusively by recorded solver artifacts.

The adapter is isolated below ``/api/demo/four-round``. It never submits a
solver job and never mutates the formal ResearchService state.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse

from topoptpilot_desktop import __version__
from topoptpilot.reports.generator import ResearchReportGenerator


router = APIRouter(prefix="/api/demo/four-round", tags=["desktop-demo-edition"])
DEMO_RESEARCH_ID = "DEMO-R-001"
DEMO_RUN_ID = "demo-basic-round1"
_ROUND_BY_STAGE = {2: "round2", 3: "round3", 4: "round4_final"}
_SNAPSHOT_PATTERN = re.compile(r"snapshots/iter_\d{4}_(?:density|von_mises)\.bin|snapshots/iter_\d{4}_matlab\.png")


def _resource_root() -> Path:
    configured = os.environ.get("TOPPILOT_RESOURCE_ROOT")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[1]


def _artifact_root() -> Path:
    root = _resource_root() / "experiments_rerun"
    if not root.is_dir():
        raise HTTPException(status_code=503, detail="实验数据目录不可用")
    return root.resolve()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail=f"实验数据不可读：{path.name}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=503, detail=f"实验数据格式无效：{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ref(path: Path, relative_path: str, media_type: str) -> dict[str, Any]:
    return {"relativePath": relative_path, "sha256": _sha256(path), "mediaType": media_type, "sizeBytes": path.stat().st_size}


def _history_bytes() -> bytes:
    return json.dumps(_round_result("round1")["history"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _bytes_ref(content: bytes, relative_path: str, media_type: str) -> dict[str, Any]:
    return {"relativePath": relative_path, "sha256": hashlib.sha256(content).hexdigest(), "mediaType": media_type, "sizeBytes": len(content)}


def _round_result(run_name: str) -> dict[str, Any]:
    run_dir = _artifact_root() / run_name
    result = _read_json(run_dir / "result_summary.json")
    config = _read_json(run_dir / "config.json")
    objective = [float(value) for value in result.get("objective_history") or []]
    change = [float(value) for value in result.get("change_history") or []]
    history = [{"iteration": index + 1, "compliance": value, "change": change[index] if index < len(change) else None} for index, value in enumerate(objective)]
    return {
        "runName": run_name, "iterations": int(result.get("iterations") or len(history)),
        "compliance": float(result["objective"]), "volumeFraction": float(result["volume_fraction"]),
        "grayRatio": float(result["gray_ratio"]), "finalChange": float(result["final_change"]),
        "converged": bool(result.get("converged")), "finalBeta": float(result.get("final_beta") or 1.0),
        "history": history, "config": config,
    }


def _candidate(name: str, title: str, intent: str, purpose: str, factors: list[str]) -> dict[str, Any]:
    result = _read_json(_artifact_root() / name / "step3_result.json")
    source = f"experiments_rerun/{name}/step3_result.json"
    return {
        "source": source, "title": title, "result": result,
        "proposal": {
            "id": f"DEMO-P-{name}", "intent": intent, "purpose": purpose, "fidelity": "STEP1",
            "backend": "python", "parameters": result.get("task_params") or {},
            "estimated_cost": result.get("solve_time_seconds"), "risk": "LOW", "safety_status": "SAFE",
            "controlled_factors": factors, "status": "PLANNED",
            "evidence_source": source,
        },
    }


def _candidates() -> list[dict[str, Any]]:
    return [
        _candidate("s3_base", "基线方向", "保持无投影基线", "建立粗网格对照", []),
        _candidate("s3_cont_b2m16", "黑白化方向", "引入 beta 2→16 连续化", "降低中间密度单元占比", ["projection", "beta_max"]),
        _candidate("s3_move005", "收敛方向", "移动限步调整为 0.005", "改善末期设计变量稳定性", ["move"]),
    ]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _DemoState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.reset()

    def reset(self) -> None:
        with self.lock:
            self.engineering_started: float | None = None
            self.research_created = False
            self.phase = "IDLE"
            self.stage = 0
            self.stage_started: float | None = None
            self.events: list[dict[str, Any]] = []
            self.experiments: list[dict[str, Any]] = []
            self.event_sequence = 0
            self.gate_event_id: str | None = None

    def add_event(self, title: str, body: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self.event_sequence += 1
        event = {"id": self.event_sequence, "kind": "WORKFLOW", "title": title, "body": body, "created_at": _now(), "payload": payload or {}}
        self.events.append(event)
        return event

    def progress(self) -> float:
        if self.phase != "RUNNING" or self.stage_started is None:
            return 1.0 if self.phase in {"GATE", "COMPLETED"} else 0.0
        return min(1.0, max(0.0, (time.monotonic() - self.stage_started) / 9.0))

    def _candidate_experiment(self, item: dict[str, Any]) -> dict[str, Any]:
        proposal, result = item["proposal"], item["result"]
        return {
            "id": proposal["id"].replace("DEMO-P", "DEMO-E"), "status": "RUNNING", "fidelity": "STEP1",
            "backend": "python", "progress": 0.0, "current_iteration": 0, "parameters": proposal["parameters"],
            "purpose": proposal["purpose"], "round_number": 1, "decision_source": "HUMAN_CONFIRMED",
            "intent_source": "DOCUMENTED_EXPERIMENT", "result_source": "VERIFIED_REPLAY",
            "evidence_ids": [item["source"]], "_recorded_result": result,
        }

    def _round_experiment(self, stage: int, status: str, progress: float) -> dict[str, Any]:
        recorded = _round_result(_ROUND_BY_STAGE[stage])
        count = max(1, min(recorded["iterations"], round(recorded["iterations"] * progress))) if progress else 0
        history = recorded["history"][:count]
        result: dict[str, Any] = {"artifacts": {"history": history}}
        if history:
            result["objective"] = {"compliance": history[-1]["compliance"]}
        if status == "SUCCESS":
            quality: dict[str, Any] = {"gray_ratio": recorded["grayRatio"]}
            if stage == 4:
                quality["connected_components"] = int(_read_json(_artifact_root() / "final_acceptance.json")["checks"]["拓扑形态"]["value"]["connected_components"])
            result.update({
                "objective": {"compliance": recorded["compliance"]},
                "constraints": {"volume_fraction": recorded["volumeFraction"]}, "quality": quality,
                "evaluation": {"converged": recorded["converged"], "final_change": recorded["finalChange"]},
            })
        return {
            "id": f"DEMO-E-STEP{stage}", "status": status, "fidelity": f"STEP{stage}", "backend": "matlab",
            "progress": progress, "current_iteration": count, "parameters": recorded["config"],
            "purpose": {2: "同参数复现", 3: "投影连续化", 4: "收敛性修复"}[stage], "round_number": stage,
            "decision_source": "HUMAN_CONFIRMED", "intent_source": "DOCUMENTED_EXPERIMENT",
            "result_source": "VERIFIED_REPLAY", "evidence_ids": [f"experiments_rerun/{recorded['runName']}/result_summary.json"],
            "result": result,
        }

    def start_stage(self, stage: int) -> None:
        self.stage, self.phase, self.stage_started, self.gate_event_id = stage, "RUNNING", time.monotonic(), None
        new_items = [self._candidate_experiment(item) for item in _candidates()] if stage == 1 else [self._round_experiment(stage, "RUNNING", 0.0)]
        self.experiments.extend(new_items)
        self.add_event("FIDELITY_STAGE_STARTED", f"Step{stage} 已启动。", {"stage_code": f"STEP{stage}", "experiment_ids": [item["id"] for item in new_items]})

    def materialize(self) -> None:
        if self.phase != "RUNNING":
            return
        progress = self.progress()
        stage_ids = [item["id"] for item in self.experiments if item.get("round_number") == self.stage]
        for index, item in enumerate(self.experiments):
            if item["id"] not in stage_ids:
                continue
            if self.stage == 1:
                item["progress"] = progress
                item["current_iteration"] = round(int(item["_recorded_result"]["iterations"]) * progress)
            else:
                self.experiments[index] = self._round_experiment(self.stage, "RUNNING", progress)
        if progress < 1.0:
            return
        for index, item in enumerate(self.experiments):
            if item["id"] not in stage_ids:
                continue
            if self.stage == 1:
                recorded = item.pop("_recorded_result")
                item.update({"status": "SUCCESS", "progress": 1.0, "current_iteration": int(recorded["iterations"])})
                item["result"] = {
                    "objective": {"compliance": float(recorded["compliance"])},
                    "constraints": {"volume_fraction": float(recorded["volume_fraction"])},
                    "quality": {"gray_ratio": float(recorded["gray_ratio"]), "connected_components": int(recorded["connected_components"])},
                    "evaluation": {"converged": bool(recorded["converged"]), "final_change": float(recorded["final_change"])},
                    "artifacts": {"history": recorded.get("history") or []},
                }
            else:
                self.experiments[index] = self._round_experiment(self.stage, "SUCCESS", 1.0)
        best = stage_ids[0]
        best_item = next(item for item in self.experiments if item["id"] == best)
        weak_points = {
            1: ["基线方向用于建立后续同参数复现链。"],
            2: ["同参数结果保持一致，下一步只引入投影连续化。"],
            3: ["灰度率已显著降低，但最终设计变量变化量仍需改善。"],
            4: ["求解器已判定收敛，进入最终工程审查。"],
        }[self.stage]
        gate = self.add_event("FIDELITY_STAGE_AWAITING_DECISION", f"Step{self.stage} 已完成，等待实验者决定。", {
            "stage_code": f"STEP{self.stage}", "internal_fidelity": f"STEP{self.stage}", "round": self.stage,
            "experiment_ids": stage_ids, "best_experiment_id": best,
            "result": {"best_compliance": best_item["result"]["objective"]["compliance"], "failed": 0, "weak_points": weak_points},
        })
        self.gate_event_id, self.phase = str(gate["id"]), "GATE"

    @staticmethod
    def _public(item: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if item is None else {key: value for key, value in item.items() if not key.startswith("_")}

    def workflow(self) -> dict[str, Any]:
        percent = round(self.progress() * 100) if self.phase == "RUNNING" else (100 if self.phase in {"GATE", "COMPLETED"} else 0)
        steps = []
        for number in range(1, 5):
            done = number < self.stage or self.phase == "COMPLETED" or (number == self.stage and self.phase == "GATE")
            status = "completed" if done else ("active" if number == self.stage and self.phase == "RUNNING" else "pending")
            steps.append({"id": f"step{number}", "label": f"Step{number}", "status": status, "result": "真实结果已完成" if done else None, "reflection": None, "evidenceIds": [], "experimentIds": [], "nextAction": "等待人工审查" if number == self.stage and self.phase == "GATE" else None})
        stage_name = "completed" if self.phase == "COMPLETED" else ("experiments" if self.phase == "RUNNING" else "approval")
        return {"round": max(1, self.stage), "stage": stage_name, "percent": percent, "steps": steps, "budgetUsed": min(4, self.stage), "budgetTotal": 4}

    def research(self) -> dict[str, Any]:
        self.materialize()
        proposals = [item["proposal"] for item in _candidates()]
        workflow_defaults: dict[str, Any] = {}
        if self.phase == "PLAN":
            workflow_defaults = {"candidate_plan": {"status": "AWAITING_CONFIRMATION", "proposal_ids": [item["id"] for item in proposals], "recommended_proposal_id": proposals[0]["id"]}}
        public_experiments = [self._public(item) for item in self.experiments]
        best = next((item for item in reversed(public_experiments) if item and item.get("status") == "SUCCESS"), None)
        completed = self.phase == "COMPLETED"
        return {
            "id": DEMO_RESEARCH_ID, "name": "三维悬臂梁四轮优化",
            "goal": "在体积分数 0.40 约束下完成三维悬臂梁拓扑优化，并降低灰度率、改善收敛性。",
            "hypothesis": "投影连续化可降低灰度率，移动限步衰减可改善末期收敛。", "locale": "zh-CN",
            "status": "COMPLETED" if completed else ("RUNNING" if self.phase == "RUNNING" else "READY"),
            "mode": "DEEP_OPTIMIZATION", "constraints": {"volume_fraction": 0.4, "volfrac": 0.4, "gray_max": 0.15, "connected": True},
            "geometry": {"type": "cantilever", "dimension": "3d", "grid": [48, 16, 12]},
            "material": {"name": "结构钢", "E": 200000000000.0, "nu": 0.3, "density": 7850, "yield_strength": 250000000.0},
            "contract": {"source": "engineering-baseline", "solver": "MATLAB"}, "defaults": {"autonomous_workflow": workflow_defaults},
            "budgets": {}, "current_round": max(1, self.stage), "budget_total": 4, "budget_used": min(4, self.stage),
            "experiments": public_experiments, "events": list(self.events), "decisions": [], "proposals": proposals,
            "best_experiment": best, "termination_reason": "四轮流程与六项工程验收完成" if completed else None,
            "workflow": self.workflow(),
        }


state = _DemoState()


def _engineering_public() -> dict[str, Any]:
    recorded = _round_result("round1")
    progress = 0.0 if state.engineering_started is None else min(1.0, (time.monotonic() - state.engineering_started) / 10.0)
    current = max(0, min(recorded["iterations"], round(recorded["iterations"] * progress)))
    run_dir = _artifact_root() / "round1"
    files = [_ref(run_dir / "result_manifest.json", "result_manifest.json", "application/json"), _ref(run_dir / "final_density.bin", "final_density.bin", "application/octet-stream"), _ref(run_dir / "final_von_mises.bin", "final_von_mises.bin", "application/octet-stream"), _ref(run_dir / "result_summary.json", "result_summary.json", "application/json"), _bytes_ref(_history_bytes(), "history.json", "application/json")] if progress >= 1.0 else []
    return {
        "runId": DEMO_RUN_ID, "ownerType": "project", "ownerId": "engineering-ui", "lane": "local-matlab",
        "status": "completed" if progress >= 1.0 else "running", "configDigest": "464820cc95521f75",
        "metrics": {"iteration": current, "compliance": recorded["history"][current - 1]["compliance"] if current else None, "volumeFraction": recorded["volumeFraction"] if progress >= 1.0 else None, "grayRatio": recorded["grayRatio"] if progress >= 1.0 else None},
        "snapshots": [], "files": files, "provenance": {"resultKind": "solver", "backend": "local-matlab", "solver": "MATLAB", "configHash": "464820cc95521f75"},
    }


def _engineering_events() -> list[dict[str, Any]]:
    current = int(_engineering_public()["metrics"]["iteration"] or 0)
    frames = [item for item in (_read_json(_artifact_root() / "round1" / "snapshots" / "manifest.json").get("frames") or []) if int(item["iteration"]) <= current]
    events = []
    for seq, frame in enumerate(frames, 1):
        iteration = int(frame["iteration"])
        events.append({"seq": seq, "type": "progress", "iteration": iteration, "metrics": {"iteration": iteration, "compliance": frame["objective"], "volumeFraction": frame["volume_fraction"], "grayRatio": frame["gray_ratio"]}, "snapshot": {"densityPath": f"snapshots/{frame['density_file']}", "stressPath": f"snapshots/{frame['stress_file']}", "renderPath": f"snapshots/{frame['render_file']}", "shape": [16, 48, 12], "dimension": "3d"}})
    return events


def _require_research(research_id: str) -> None:
    if research_id != DEMO_RESEARCH_ID or not state.research_created:
        raise HTTPException(status_code=404, detail="research not found")


@router.get("")
def four_round_demo_manifest() -> dict[str, Any]:
    acceptance = _read_json(_artifact_root() / "final_acceptance.json")
    return {"versionLabel": f"TopOptPilot {__version__} 演示版", "rounds": [_round_result(name) for name in ["round1", "round2", "round3", "round4_final"]], "candidates": _candidates(), "acceptance": acceptance, "allPassed": bool(acceptance.get("all_pass"))}


@router.post("/reset")
def demo_reset() -> dict[str, bool]:
    state.reset()
    return {"reset": True}


@router.get("/research")
def demo_research_list() -> list[dict[str, Any]]:
    with state.lock:
        return [state.research()] if state.research_created else []


@router.get("/research/{research_id}")
def demo_research_get(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    with state.lock:
        return state.research()


@router.post("/engineering/runs", status_code=202)
def demo_engineering_run() -> dict[str, Any]:
    with state.lock:
        state.reset()
        state.engineering_started = time.monotonic()
        return _engineering_public()


@router.get("/engineering/runs/{run_id}")
def demo_engineering_run_get(run_id: str) -> dict[str, Any]:
    if run_id != DEMO_RUN_ID or state.engineering_started is None:
        raise HTTPException(status_code=404, detail="engineering run not found")
    return _engineering_public()


@router.get("/engineering/runs/{run_id}/events")
def demo_engineering_run_events(run_id: str, after_seq: int = Query(default=0, ge=0)) -> dict[str, Any]:
    if run_id != DEMO_RUN_ID:
        raise HTTPException(status_code=404, detail="engineering run not found")
    return {"runId": run_id, "events": [item for item in _engineering_events() if int(item["seq"]) > after_seq]}


@router.get("/engineering/runs/{run_id}/files/{relative_path:path}")
def demo_engineering_file(run_id: str, relative_path: str):
    if run_id != DEMO_RUN_ID:
        raise HTTPException(status_code=404, detail="engineering run not found")
    normalized = PurePosixPath(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise HTTPException(status_code=400, detail="invalid artifact path")
    if relative_path == "history.json":
        return PlainTextResponse(_history_bytes(), media_type="application/json")
    allowed_final = {"result_manifest.json", "final_density.bin", "final_von_mises.bin", "result_summary.json"}
    if relative_path not in allowed_final and not _SNAPSHOT_PATTERN.fullmatch(relative_path):
        raise HTTPException(status_code=404, detail="artifact not found")
    run_dir = (_artifact_root() / "round1").resolve()
    target = (run_dir / Path(*normalized.parts)).resolve()
    if run_dir not in target.parents or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(target)


@router.post("/research/from-engineering-run/{run_id}")
def demo_research_from_engineering(run_id: str) -> dict[str, Any]:
    if run_id != DEMO_RUN_ID or _engineering_public()["status"] != "completed":
        raise HTTPException(status_code=409, detail="engineering baseline is not complete")
    with state.lock:
        state.research_created, state.phase, state.stage = True, "IDLE", 0
        state.add_event("ENGINEERING_BASELINE_IMPORTED", "工程结果已确认为科研基线。", {"run_id": run_id})
        return state.research()


@router.post("/research/{research_id}/autonomous")
def demo_autonomous(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    with state.lock:
        if state.phase not in {"IDLE", "PLAN"}:
            raise HTTPException(status_code=409, detail="current step is not ready")
        state.phase, state.stage = "PLAN", 1
        state.add_event("CANDIDATE_PLAN_READY", "Step1 三个候选方案已生成，等待实验者确认。")
        return state.research()


@router.post("/research/{research_id}/candidate-plan/confirm")
def demo_candidate_confirm(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    with state.lock:
        if state.phase != "PLAN":
            raise HTTPException(status_code=409, detail="candidate plan is not awaiting confirmation")
        state.start_stage(1)
        return state.research()


@router.post("/research/{research_id}/fidelity-stage-decision")
def demo_stage_decision(research_id: str, request: dict[str, Any]) -> dict[str, Any]:
    _require_research(research_id)
    with state.lock:
        state.materialize()
        if state.phase != "GATE" or not state.gate_event_id:
            raise HTTPException(status_code=409, detail="no stage decision is pending")
        action = str(request.get("action") or "")
        state.add_event("FIDELITY_STAGE_DECISION", action, {"gate_event_id": state.gate_event_id, "action": action})
        if action == "REPEAT_STAGE":
            state.start_stage(state.stage)
        elif action == "ADVANCE_STAGE" and state.stage < 4:
            state.start_stage(state.stage + 1)
        elif action == "APPROVE_FINAL" and state.stage == 4:
            state.phase = "COMPLETED"
        else:
            raise HTTPException(status_code=422, detail="invalid stage decision")
        return state.research()


@router.post("/research/{research_id}/finish")
def demo_finish(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    with state.lock:
        state.materialize()
        if state.stage != 4 or state.phase != "GATE":
            raise HTTPException(status_code=409, detail="Step4 review is not complete")
        if state.gate_event_id:
            state.add_event("FIDELITY_STAGE_DECISION", "APPROVE_FINAL", {"gate_event_id": state.gate_event_id, "action": "APPROVE_FINAL"})
        state.phase = "COMPLETED"
        state.add_event("RESEARCH_COMPLETED", "四轮流程及最终验收已完成。")
        return state.research()


@router.get("/research/{research_id}/events")
def demo_research_events(research_id: str, after: int = Query(default=0, ge=0)) -> list[dict[str, Any]]:
    _require_research(research_id)
    with state.lock:
        state.materialize()
        return [item for item in state.events if int(item["id"]) > after]


@router.get("/research/{research_id}/artifacts")
def demo_research_artifacts(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    research = state.research()
    return {"researchId": research_id, "experiments": [{"experimentId": item["id"], "status": item["status"], "fidelity": item["fidelity"], "backend": item["backend"], "provenance": {"resultKind": "solver", "source": (item.get("evidence_ids") or [""])[0]}, "files": [], "metrics": {"compliance": item.get("result", {}).get("objective", {}).get("compliance"), "grayRatio": item.get("result", {}).get("quality", {}).get("gray_ratio")}} for item in research["experiments"]]}


@router.get("/researches/{research_id}/optimization-config")
def demo_optimization_config(research_id: str) -> dict[str, Any]:
    _require_research(research_id)
    return {"dimension": "3d", "nelx": 48, "nely": 16, "nelz": 12, "volfrac": 0.4, "penal": 3, "rmin": 2, "maxIterations": 80, "minIterations": 10, "bcType": "cantilever", "material": {"id": "structural-steel", "name": "结构钢", "E": 200000000000, "nu": 0.3, "density": 7850, "yieldStrength": 250000000}, "filterStrategy": "fixed", "accuracy": "high", "solverLane": "local-matlab"}


def _experiment_run(experiment_id: str) -> str:
    run_name = {"DEMO-E-STEP2": "round2", "DEMO-E-STEP3": "round3", "DEMO-E-STEP4": "round4_final"}.get(experiment_id)
    if not run_name:
        raise HTTPException(status_code=404, detail="visualization not available")
    return run_name


@router.get("/research/{research_id}/experiments/{experiment_id}/visualization")
def demo_visualization(research_id: str, experiment_id: str) -> dict[str, Any]:
    _require_research(research_id)
    experiment = next((item for item in state.research()["experiments"] if item["id"] == experiment_id), None)
    if not experiment or experiment["status"] != "SUCCESS":
        raise HTTPException(status_code=409, detail="visualization is not complete")
    run_name = _experiment_run(experiment_id)
    recorded = _round_result(run_name)
    connected = int(_read_json(_artifact_root() / "final_acceptance.json")["checks"]["拓扑形态"]["value"]["connected_components"]) if run_name == "round4_final" else None
    return {"researchId": research_id, "experimentId": experiment_id, "dimension": "3d", "shape": [16, 48, 12], "encoding": "float32-le", "order": "F", "hasStress": True, "history": recorded["history"], "metrics": {"compliance": recorded["compliance"], "volumeFraction": recorded["volumeFraction"], "grayRatio": recorded["grayRatio"], "connectedComponents": connected}, "config": recorded["config"], "backend": "matlab", "fidelity": experiment_id.replace("DEMO-E-", ""), "status": "SUCCESS", "evidenceIds": [f"experiments_rerun/{run_name}/result_summary.json"], "resultSource": "VERIFIED_REPLAY"}


@router.get("/research/{research_id}/experiments/{experiment_id}/visualization/{field}")
def demo_visualization_field(research_id: str, experiment_id: str, field: str):
    _require_research(research_id)
    experiment = next((item for item in state.research()["experiments"] if item["id"] == experiment_id), None)
    if not experiment or experiment["status"] != "SUCCESS":
        raise HTTPException(status_code=409, detail="visualization is not complete")
    if field not in {"density", "stress"}:
        raise HTTPException(status_code=404, detail="field not found")
    filename = "final_density.bin" if field == "density" else "final_von_mises.bin"
    return FileResponse(_artifact_root() / _experiment_run(experiment_id) / filename, media_type="application/octet-stream")


def _report_markdown() -> str:
    acceptance = _read_json(_artifact_root() / "final_acceptance.json")
    rows = []
    for stage, run_name in enumerate(["round1", "round2", "round3", "round4_final"], 1):
        item = _round_result(run_name)
        rows.append(f"| Step{stage} | {item['compliance']:.9f} | {item['volumeFraction']:.6f} | {item['grayRatio']:.6f} | {str(item['converged']).lower()} |")
    checks = "\n".join(f"- {name}：{'达到' if value.get('pass') else '需要复核'}" for name, value in (acceptance.get("checks") or {}).items())
    return "\n".join(["# 三维悬臂梁四轮优化报告", "", f"配置哈希：`{acceptance.get('config_hash', '')}`", "", "| 阶段 | 柔度 | 体积分数 | 灰度率 | 收敛 |", "|---|---:|---:|---:|:---:|", *rows, "", "## 最终工程验收", "", checks, ""])


@router.get("/research/{research_id}/reports/preview")
def demo_report_preview(research_id: str) -> dict[str, str]:
    _require_research(research_id)
    return {"markdown": _report_markdown(), "markdownPath": "", "pdfPath": ""}


@router.post("/research/{research_id}/reports/export")
def demo_report_export(research_id: str, request: dict[str, Any]) -> dict[str, Any]:
    _require_research(research_id)
    output = Path(str(request.get("outputDirectory") or "")).expanduser().resolve()
    if not output.is_dir():
        raise HTTPException(status_code=422, detail="报告输出目录不存在")
    name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(request.get("name") or "TopOptPilot_Report")).strip("._")
    if not name:
        raise HTTPException(status_code=422, detail="报告名称无效")
    markdown_path, pdf_path = output / f"{name}.md", output / f"{name}.pdf"
    asset_directory = output / f"{name}_assets"
    targets = [markdown_path, pdf_path, asset_directory]
    if not bool(request.get("overwrite")) and any(path.exists() for path in targets):
        raise HTTPException(status_code=409, detail="同名报告已存在")
    asset_directory.mkdir(parents=False, exist_ok=True)
    markdown = _report_markdown()
    markdown_path.write_text(markdown, encoding="utf-8")
    ResearchReportGenerator.render_pdf(markdown, pdf_path)
    final_dir = _artifact_root() / "round4_final"
    for filename in ("density.png", "convergence.png"):
        shutil.copy2(final_dir / filename, asset_directory / filename)
    generated = [markdown_path, pdf_path, asset_directory / "density.png", asset_directory / "convergence.png"]
    return {
        "markdownPath": str(markdown_path), "pdfPath": str(pdf_path), "assetDirectory": str(asset_directory),
        "files": [{"path": str(path), "sizeBytes": path.stat().st_size, "sha256": _sha256(path)} for path in generated],
    }


@router.get("/report/{research_id}")
def demo_report_download(research_id: str):
    _require_research(research_id)
    return PlainTextResponse(_report_markdown(), media_type="text/markdown", headers={"Content-Disposition": "attachment; filename=TopOptPilot-four-round-report.md"})
