"""Single application service shared by the Workspace and the test API."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
import zipfile
import hashlib
import platform
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from topoptpilot.executor import ExperimentQueue
from topoptpilot.executor.cache import ResultCache
from topoptpilot.executor.executor import build_solver_task
from topoptpilot.memory import ResearchStateStore
from topoptpilot.memory.research_state import utc_now
from topoptpilot.fidelity import FidelityManager
from topoptpilot.orchestrator import ResearchOrchestrator
from topoptpilot.policy.approval_policy import requires_human_approval
from topoptpilot.schemas import (
    DecisionStatus, EventKind, ExperimentCreate, ExperimentStatus,
    ResearchCreate, WorkspaceCommandResult,
)
from topoptpilot.tools import ResearchTools
from topoptpilot.agent_runtime import PiBridge
from agent.llm.client import PiAgentClient
from mcp.matlab_mcp import MatlabMcpError, MatlabMcpWorker


STATUS_SYMBOLS = {
    "WAITING": "○", "RUNNING": "▶", "SUCCESS": "✓",
    "FAILED": "✗", "CANCELLED": "⚠",
}


class ResearchService:
    def __init__(self, data_dir: str | Path | None = None, max_workers: int = 2,
                 agent_client: PiAgentClient | None = None):
        configured_data = data_dir or os.environ.get("TOPPILOT_DATA_DIR") or "topoptpilot/storage"
        self.data_dir = Path(configured_data).resolve()
        self.project_root = Path(os.environ.get(
            "TOPPILOT_RESOURCE_ROOT", Path(__file__).resolve().parents[2])).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ResearchStateStore(self.data_dir / "research.db")
        self.queue = ExperimentQueue(self.data_dir / "progress", max_workers=max_workers)
        self.matlab_worker = MatlabMcpWorker(self.data_dir, self.project_root)
        self.cache = ResultCache(self.data_dir / "cache")
        self.orchestrator = ResearchOrchestrator()
        self.agent_client = agent_client or PiAgentClient()
        self.tools = ResearchTools(self)
        self.pi_runtime = None
        self.pi_runtime_error = None
        try:
            self.pi_runtime = PiBridge(self)
        except Exception as exc:
            self.pi_runtime_error = str(exc)
        self._completion_lock = threading.RLock()

    def health(self) -> dict[str, Any]:
        runtime = (self.pi_runtime.health() if self.pi_runtime else
                   {"available": False, "status": "unavailable", "last_error": self.pi_runtime_error})
        matlab_mcp = self.matlab_worker.health()
        return {"status": "ok", "solver_2d": True, "python_3d": True,
                "matlab": matlab_mcp["state"] != "UNAVAILABLE", "matlab_mcp": matlab_mcp,
                "database": str(self.store.db_path),
                "agent_framework": "official-pi-rpc" if runtime.get("available") else "rule-safe-mode",
                "agent_model": self.agent_client.model,
                "agent_configured": bool(self.agent_client.api_key),
                "python_agent_fallback": self.agent_client.framework, "pi_rpc": runtime}

    @staticmethod
    def _matlab_available() -> bool:
        try:
            from solver.matlab_backend import is_matlab_available
            return bool(is_matlab_available())
        except Exception:
            return False

    def create_research(self, request: ResearchCreate | dict[str, Any]) -> dict[str, Any]:
        model = request if isinstance(request, ResearchCreate) else ResearchCreate.model_validate(request)
        research_id = self._next_research_id()
        payload = model.model_dump()
        payload["budgets"] = model.normalized_budgets()
        research = self.store.create_research({"id": research_id, **payload})
        self.store.append_event(research_id, EventKind.USER.value, "RESEARCH GOAL",
                                f"{model.goal}\n\nConstraints: {json.dumps(model.constraints, ensure_ascii=False)}")
        self.store.append_event(research_id, EventKind.PLANNER.value, "ROUND 1 STRATEGY",
                                self.orchestrator.initial_plan(research))
        return self.get_research(research_id)

    def submit_proposal(self, research_id: str, proposal_id: str) -> dict[str, Any]:
        """Atomically validate and submit one deterministic-policy proposal."""
        research = self._require_research(research_id)
        proposal = self.store.get_proposal(proposal_id)
        if not proposal or proposal["research_id"] != research_id:
            raise KeyError(f"Proposal {proposal_id} does not exist")
        if proposal.get("experiment_id"):
            return {"proposal": proposal, "experiment": self.get_experiment(proposal["experiment_id"])}
        if proposal["safety_status"] == "REJECTED":
            raise ValueError("Safety Policy rejected this proposal")
        budget = FidelityManager.budget(research, self.store.list_experiments(research_id))
        fidelity = str(proposal["fidelity"])
        if budget["remaining"]["total"] <= 0 or budget["remaining"].get(fidelity, 0) <= 0:
            raise ValueError(f"No remaining {fidelity} budget")
        if budget["time_remaining"] is not None and budget["time_remaining"] <= 0:
            raise ValueError("Research time budget is exhausted")
        if fidelity == "F3" and self.pi_runtime:
            threading.Thread(target=self.pi_runtime.reviewer.review,
                             args=(research_id, "HIGH_FIDELITY_ESCALATION", proposal_id),
                             daemon=True).start()
        request = ExperimentCreate(
            purpose=proposal["purpose"], fidelity={
                "F0": "F0 — 2D Coarse", "F1": "F1 — 2D Fine",
                "F2": "F2 — Python 3D", "F3": "F3 — MATLAB 3D",
            }[fidelity], mesh_level=FidelityManager.mesh_level(fidelity),
            backend=proposal["backend"], parameters=proposal["parameters"],
            warm_start=proposal.get("source_experiment"),
            requires_approval=bool(proposal["approval_required"]),
            proposal_id=proposal_id, intent=proposal["intent"],
        )
        experiment = self.create_experiment(research_id, request)
        self.store.update_proposal(proposal_id, status=(
            "PENDING_HUMAN_APPROVAL" if experiment.get("decision_id") else "SUBMITTED"),
            experiment_id=experiment["id"])
        return {"proposal": self.store.get_proposal(proposal_id),
                "experiment": self.get_experiment(experiment["id"])}

    def start_autonomous_research(self, research_id: str) -> dict[str, Any]:
        """Start the Pi-owned closed loop; Policy remains the sole parameter compiler."""
        research = self._require_research(research_id)
        self.store.update_research(research_id, mode="AUTONOMOUS", status="RUNNING")
        self.store.append_event(research_id, EventKind.SYSTEM.value, "ROUND_STARTED",
                                f"Autonomous round {int(research.get('current_round', 0)) + 1} started.")
        language = "Simplified Chinese" if research.get("locale", "zh-CN") == "zh-CN" else "English"
        prompt = (
            "You are the primary Pi Research Agent. Begin or continue an autonomous topology-"
            "optimization campaign. First call research_get_context and research_get_budget. "
            "Choose one scientific intent, call policy_compile_intent, preview every returned proposal, "
            "then submit the safe bounded batch within the available budget. Never provide numeric solver "
            "parameters directly. Await all FEM evidence "
            f"before the next decision. Stop on goal, plateau, or exhausted budget. Reply in {language}."
        )
        threading.Thread(target=self._send_pi_or_fallback,
                         args=(research_id, prompt, "experiment-planning"), daemon=True).start()
        return self.get_research(research_id)

    def _send_pi_or_fallback(self, research_id: str, prompt: str, skill: str) -> None:
        try:
            if not self.pi_runtime:
                raise RuntimeError("official Pi runtime unavailable")
            self.pi_runtime.send(research_id, prompt, skill, fallback_on_error=True)
        except Exception as exc:
            self.store.append_event(research_id, EventKind.SYSTEM.value, "PI SAFE MODE",
                                    f"Qwen/Pi unavailable: {exc}. Deterministic rule policy took over.")
            self._safe_mode_next(research_id)

    def _safe_mode_next(self, research_id: str) -> None:
        research = self._require_research(research_id)
        if research["status"] == "STOPPED" or research.get("termination_reason"):
            return
        experiments = self.store.list_experiments(research_id)
        budget = FidelityManager.budget(research, experiments)
        if budget["remaining"]["total"] <= 0:
            self.store.update_research(research_id, status="STOPPED",
                                       termination_reason="BUDGET_EXHAUSTED")
            return
        completed = [item for item in experiments if item.get("result")]
        if not completed:
            intent = {"intent": "ESTABLISH_BASELINE"}
        else:
            last = completed[-1]
            quality = last["result"].get("quality", {})
            if quality.get("connected_components", 1) != 1:
                intent = {"intent": "RESTORE_CONNECTIVITY", "source_experiment": last["id"]}
            elif quality.get("gray_ratio", 1.0) > research["constraints"].get("gray_max", 0.05):
                intent = {"intent": "REDUCE_GRAYNESS", "source_experiment": last["id"]}
            else:
                intent = {"intent": "UPGRADE_FIDELITY", "source_experiment": last["id"]}
        proposals = self.tools.policy_compile_intent(research_id, **intent)
        if not proposals:
            self.store.update_research(research_id, status="STOPPED", termination_reason="PLATEAU")
            self.store.append_event(research_id, EventKind.SYSTEM.value, "SAFE MODE STOPPED",
                                    "Policy produced no novel controlled experiment.")
            return
        try:
            self.submit_proposal(research_id, proposals[0]["id"])
        except ValueError as exc:
            self.store.append_event(research_id, EventKind.SYSTEM.value, "SAFE MODE STOPPED", str(exc))

    def _termination_reason(self, research_id: str) -> str | None:
        research = self._require_research(research_id)
        experiments = self.store.list_experiments(research_id)
        budget = FidelityManager.budget(research, experiments)
        if budget["remaining"]["total"] <= 0:
            return "BUDGET_EXHAUSTED"
        if budget["time_remaining"] is not None and budget["time_remaining"] <= 0:
            return "BUDGET_EXHAUSTED"
        successful = [item for item in experiments if item.get("result") and item["status"] == "SUCCESS"]
        if successful:
            required = str(research["constraints"].get("required_fidelity", "F2"))
            rank = {"F0": 0, "F1": 1, "F2": 2, "F3": 3}
            eligible = [item for item in successful
                        if rank.get(str(item["fidelity"]).split()[0], 0) >= rank.get(required, 2)]
            best = min(eligible, key=lambda item: item["result"]["objective"]["compliance"],
                       default=None)
            q = (best or {}).get("result", {}).get("quality", {})
            if (q.get("gray_ratio", 1) <= research["constraints"].get("gray_max", 0.05)
                    and (not research["constraints"].get("connected", True)
                         or q.get("connected_components") == 1)):
                return "GOAL_ACHIEVED"
        same_fidelity = [item for item in successful
                         if str(item["fidelity"]).split()[0] == str(successful[-1]["fidelity"]).split()[0]] if successful else []
        if len(same_fidelity) >= 4:
            values = [item["result"]["objective"]["compliance"] for item in same_fidelity[-4:]]
            if (max(values) - min(values)) / max(min(values), 1e-12) < 0.005:
                return "PLATEAU"
        return None

    def _next_research_id(self) -> str:
        used = {item["id"] for item in self.store.list_research()}
        number = 1
        while f"MBB-{number:03d}" in used:
            number += 1
        return f"MBB-{number:03d}"

    def list_research(self) -> list[dict[str, Any]]:
        return self.store.list_research()

    def get_research(self, research_id: str) -> dict[str, Any]:
        research = self.store.get_research(research_id)
        if not research:
            raise KeyError(f"Research {research_id} does not exist")
        research["experiments"] = self.store.list_experiments(research_id)
        for experiment in research["experiments"]:
            if experiment["run_id"] and experiment["status"] in {"WAITING", "RUNNING"}:
                self._sync_progress(experiment)
        research["experiments"] = self.store.list_experiments(research_id)
        research["events"] = self.store.list_events(research_id)
        research["decisions"] = self.store.list_decisions(research_id)
        successful = [e for e in research["experiments"] if e["status"] == "SUCCESS" and e["result"]]
        rank = {"F0": 0, "F1": 1, "F2": 2, "F3": 3}
        highest = max((rank.get(str(item["fidelity"]).split()[0], 0) for item in successful), default=0)
        comparable = [item for item in successful
                      if rank.get(str(item["fidelity"]).split()[0], 0) == highest]
        research["best_experiment"] = min(
            comparable, key=lambda e: e["result"].get("objective", {}).get("compliance", float("inf")),
            default=None,
        )
        return research

    def create_experiment(self, research_id: str,
                          request: ExperimentCreate | dict[str, Any]) -> dict[str, Any]:
        research = self._require_research(research_id)
        if research["budget_used"] >= research["budget_total"]:
            raise ValueError("Research budget is exhausted")
        model = request if isinstance(request, ExperimentCreate) else ExperimentCreate.model_validate(request)
        code = str(model.fidelity).split()[0]
        budget = FidelityManager.budget(research, self.store.list_experiments(research_id))
        if code in {"F0", "F1", "F2", "F3"} and budget["remaining"].get(code, 0) <= 0:
            raise ValueError(f"No remaining {code} budget")
        if budget["time_remaining"] is not None and budget["time_remaining"] <= 0:
            raise ValueError("Research time budget is exhausted")
        parameters = {**model.parameters, **research["locks"]}
        experiment_id = self._next_experiment_id(research_id)
        draft = {"id": experiment_id, "research_id": research_id, **model.model_dump(),
                 "parameters": parameters}
        safety = self.orchestrator.inspect_proposal(draft)
        if not safety["safe"]:
            self.store.append_event(research_id, EventKind.SAFETY.value, "PROPOSAL REJECTED",
                                    str(safety["reason"]), payload=safety)
            raise ValueError(f"Safety Policy rejected proposal: {safety['reason']}")
        requires_approval = model.requires_approval or bool(safety["requires_approval"]) or \
            requires_human_approval(research["mode"], str(safety["risk"]), model.fidelity)
        experiment = self.store.create_experiment({
            **draft, "status": ExperimentStatus.WAITING.value, "safety": safety["risk"],
        })
        body = (f"Purpose: {model.purpose}\n\nFidelity: {model.fidelity}\n\n"
                f"Parameters: {json.dumps(parameters, ensure_ascii=False)}")
        self.store.append_event(research_id, EventKind.SAFETY.value, f"PROPOSAL {experiment_id}",
                                f"Risk: {safety['risk']}\n\n{safety['reason']}", experiment_id, safety)
        self.store.append_event(research_id, EventKind.EXPERIMENT.value,
                                f"PROPOSED EXPERIMENT {experiment_id}", body, experiment_id)
        if requires_approval or research["mode"] == "COPILOT":
            decision_id = f"D-{uuid.uuid4().hex[:8].upper()}"
            self.store.create_decision({
                "id": decision_id, "research_id": research_id, "experiment_id": experiment_id,
                "intent": "RUN_EXPERIMENT", "reason": model.purpose,
                "proposal": {"parameters": parameters, "fidelity": model.fidelity},
                "risk": safety["risk"], "status": DecisionStatus.PENDING.value,
            })
            experiment["decision_id"] = decision_id
        else:
            self.run_experiment(experiment_id)
        return experiment

    def _next_experiment_id(self, research_id: str) -> str:
        number = len(self.store.list_experiments(research_id)) + 1
        while self.store.get_experiment(f"E{number:02d}") is not None:
            number += 1
        return f"E{number:02d}"

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        if not experiment:
            raise KeyError(f"Experiment {experiment_id} does not exist")
        if experiment["run_id"] and experiment["status"] in {"WAITING", "RUNNING"}:
            self._sync_progress(experiment)
            experiment = self.store.get_experiment(experiment_id)
        return experiment

    def run_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        research = self._require_research(experiment["research_id"])
        if research["status"] in {"PAUSED", "STOPPED"}:
            raise ValueError(f"Research is {research['status'].lower()}")
        if experiment["status"] not in {"WAITING", "FAILED", "CANCELLED"}:
            return experiment
        task = build_solver_task(experiment, research)
        if experiment.get("warm_start"):
            source = self.store.get_experiment(experiment["warm_start"])
            density = ((source or {}).get("result") or {}).get("artifacts", {}).get("density")
            if density is not None:
                task["params"]["initial_density"] = density
        cache_task = {**task, "backend": experiment["backend"]}
        cached = self.cache.get(cache_task)
        if experiment["backend"] == "matlab" and cached is not None:
            backend = str((cached.get("solver") or {}).get("backend", ""))
            if not backend.startswith("matlab_mcp_"):
                cached = None
        if cached is not None:
            from concurrent.futures import Future
            future = Future()
            future.set_result(cached)
            self.store.update_experiment(experiment_id, status="RUNNING", run_id="cache_hit",
                                         started_at=utc_now(), progress=1.0, cached=1)
            self._complete_experiment(experiment_id, "cache_hit", future, cache_task)
            return self.get_experiment(experiment_id)
        if experiment["backend"] == "matlab":
            run_id, _ = self.matlab_worker.submit(
                task, research["id"], experiment_id,
                done=lambda rid, future: self._complete_experiment(
                    experiment_id, rid, future, cache_task),
            )
            self.store.append_event(research["id"], EventKind.EXPERIMENT.value,
                                    "MATLAB MCP STARTED",
                                    "Approved task was dispatched to the restricted topopt_run_task MCP tool.",
                                    experiment_id, {"backend": "matlab_mcp", "tool": "topopt_run_task"})
        else:
            run_id = self.queue.submit(
                task, backend=experiment["backend"],
                done=lambda rid, future: self._complete_experiment(
                    experiment_id, rid, future, cache_task),
            )
        self.store.update_experiment(experiment_id, status="RUNNING", run_id=run_id,
                                     started_at=utc_now(), progress=0.0)
        self.store.update_research(research["id"], status="RUNNING",
                                   budget_used=research["budget_used"] + 1)
        self.store.append_event(research["id"], EventKind.EXPERIMENT.value,
                                f"EXPERIMENT {experiment_id} STARTED",
                                f"{experiment['fidelity']} is running in the background.", experiment_id)
        return self.get_experiment(experiment_id)

    def _sync_progress(self, experiment: dict[str, Any]) -> None:
        snapshot = self.queue.poll(experiment["run_id"])
        iteration = int(snapshot.get("iteration", experiment["current_iteration"]) or 0)
        max_iter = max(1, int(experiment["parameters"].get("max_iter", 80)))
        progress = min(1.0, iteration / max_iter)
        status = snapshot.get("status", experiment["status"])
        fields: dict[str, Any] = {"current_iteration": iteration, "progress": progress}
        if status in {"RUNNING", "WAITING"}:
            fields["status"] = status
        self.store.update_experiment(experiment["id"], **fields)

    def _complete_experiment(self, experiment_id: str, run_id: str, future: Future,
                             cache_task: dict[str, Any] | None = None) -> None:
        with self._completion_lock:
            experiment = self.store.get_experiment(experiment_id)
            if not experiment:
                return
            research = self._require_research(experiment["research_id"])
            if experiment["status"] == "CANCELLED" or research["status"] == "STOPPED":
                self.store.update_experiment(experiment_id, status="CANCELLED", completed_at=utc_now())
                self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                        f"EXPERIMENT {experiment_id} CANCELLED",
                                        "The completed worker output was discarded after /stop.", experiment_id)
                return
            try:
                result = future.result()
                analysis = self.orchestrator.analyze(research, result)
                result["evaluation"] = analysis["evaluation"]
                if run_id != "cache_hit":
                    self.cache.put(cache_task or {**build_solver_task(experiment, research),
                                                  "backend": experiment["backend"]}, result)
                result = self._persist_artifacts(research["id"], experiment_id, result)
                status = "SUCCESS" if analysis["evaluation"]["success"] else "FAILED"
                iterations = int(result.get("solver", {}).get("iterations", 0))
                self.store.update_experiment(
                    experiment_id, status=status, progress=1.0, current_iteration=iterations,
                    result=result, completed_at=utc_now(), error=None,
                )
                self.store.append_event(research["id"], EventKind.ANALYSIS.value,
                                        f"ANALYSIS {experiment_id}", analysis["analysis"],
                                        experiment_id, analysis["evaluation"])
                self.store.append_event(research["id"], EventKind.EVIDENCE.value,
                                        f"EVIDENCE {experiment_id}",
                                        "Deterministic Evaluator recorded structured FEM evidence.",
                                        experiment_id, {"objective": result.get("objective"),
                                                        "constraints": result.get("constraints"),
                                                        "quality": result.get("quality"),
                                                        "evaluation": analysis["evaluation"]})
                self.store.append_event(research["id"], EventKind.FEEDBACK.value,
                                        "NEXT DECISION", analysis["feedback"], experiment_id)
            except Exception as exc:
                self.store.update_experiment(experiment_id, status="FAILED", progress=1.0,
                                             completed_at=utc_now(), error=str(exc))
                self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                        f"EXPERIMENT {experiment_id} FAILED", str(exc), experiment_id,
                                        {"failure_type": ("MATLAB_INFRASTRUCTURE"
                                                          if isinstance(exc, MatlabMcpError)
                                                          or experiment["backend"] == "matlab"
                                                          else "INFRASTRUCTURE")})
            running = [e for e in self.store.list_experiments(research["id"])
                       if e["status"] in {"WAITING", "RUNNING"} and e["run_id"]]
            if not running:
                current = self._require_research(research["id"])
                self.store.update_research(research["id"],
                                           current_round=int(current.get("current_round", 0)) + 1)
                termination = self._termination_reason(research["id"])
                if termination:
                    self.store.update_research(research["id"], status="STOPPED",
                                               termination_reason=termination)
                    self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                            "RESEARCH TERMINATED", termination)
                    if self.pi_runtime:
                        threading.Thread(target=self.pi_runtime.reviewer.review,
                                         args=(research["id"], "RESEARCH_CONCLUSION"), daemon=True).start()
                elif current["mode"] == "AUTONOMOUS":
                    completed_items = [item for item in self.store.list_experiments(research["id"])
                                       if item.get("completed_at")]
                    completed_ids = [item["id"] for item in completed_items]
                    self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                            "EXPERIMENT_BATCH_COMPLETED",
                                            f"Completed evidence batch: {completed_ids[-6:]}")
                    prompt = (
                        f"EXPERIMENT_BATCH_COMPLETED: {completed_ids[-6:]}. Read structured results, "
                        "compare relevant history, then choose the next scientific intent. You must call "
                        "policy_compile_intent; do not invent numeric parameters. Submit the complete safe "
                        "controlled batch within budget, or state a termination reason."
                    )
                    skill = ("failure-diagnosis" if any(item["status"] == "FAILED" and item.get("result")
                                                        for item in completed_items[-6:])
                             else "hypothesis-evaluation")
                    threading.Thread(target=self._send_pi_or_fallback,
                                     args=(research["id"], prompt, skill), daemon=True).start()
                elif current["status"] != "STOPPED":
                    self.store.update_research(research["id"], status="READY")

    def _persist_artifacts(self, research_id: str, experiment_id: str,
                           result: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        directory = self.data_dir / research_id / "artifacts" / experiment_id
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = result.setdefault("artifacts", {})
        density = np.asarray(artifacts.get("density"), dtype=float)
        density_path = directory / "density.npy"
        np.save(density_path, density)
        history_path = directory / "history.json"
        history_path.write_text(json.dumps(artifacts.get("history", []), default=str), encoding="utf-8")
        solver_path = directory / "solver.json"
        solver_path.write_text(json.dumps(result.get("solver", {}), default=str), encoding="utf-8")
        log_path = directory / "log.txt"
        log_path.write_text(
            f"experiment={experiment_id}\nstatus={result.get('status')}\n"
            f"compliance={result.get('objective', {}).get('compliance')}\n"
            f"gray_ratio={result.get('quality', {}).get('gray_ratio')}\n", encoding="utf-8")
        vtk_path = directory / "density.vtk"
        self._write_density_vtk(vtk_path, density)
        artifacts.update({"density_path": str(density_path), "history_path": str(history_path),
                          "solver_output_path": str(solver_path), "log": str(log_path),
                          "vtk": str(vtk_path)})
        return result

    @staticmethod
    def _write_density_vtk(path: Path, density) -> None:
        import numpy as np
        value = np.asarray(density, dtype=float)
        if value.ndim == 2:
            value = value[None, :, :]
        nz, ny, nx = value.shape
        header = ("# vtk DataFile Version 3.0\nTopOptPilot density\nASCII\n"
                  "DATASET STRUCTURED_POINTS\n"
                  f"DIMENSIONS {nx} {ny} {nz}\nORIGIN 0 0 0\nSPACING 1 1 1\n"
                  f"POINT_DATA {value.size}\nSCALARS density float 1\nLOOKUP_TABLE default\n")
        path.write_text(header + "\n".join(f"{item:.9g}" for item in value.ravel()) + "\n",
                        encoding="utf-8")

    def approve_decision(self, decision_id: str) -> dict[str, Any]:
        decision = self._require_decision(decision_id)
        if decision["status"] != "PENDING":
            return decision
        self.store.resolve_decision(decision_id, "APPROVED")
        self.store.append_event(decision["research_id"], EventKind.HUMAN.value,
                                "HUMAN APPROVAL", f"Approved {decision['intent']}.",
                                decision.get("experiment_id"), {"decision_id": decision_id})
        if decision["experiment_id"]:
            self.run_experiment(decision["experiment_id"])
        return self._require_decision(decision_id)

    def edit_pending_experiment(self, experiment_id: str, parameters: dict[str, Any]) -> dict[str, Any]:
        experiment = self.get_experiment(experiment_id)
        decision = next((item for item in self.store.list_decisions(experiment["research_id"])
                         if item.get("experiment_id") == experiment_id and item["status"] == "PENDING"), None)
        if not decision:
            raise ValueError("Only a pending proposal can be edited")
        merged = {**experiment["parameters"], **parameters,
                  **self._require_research(experiment["research_id"])["locks"]}
        safety = self.orchestrator.inspect_proposal({**experiment, "parameters": merged})
        if not safety["safe"]:
            self.store.append_event(experiment["research_id"], EventKind.SAFETY.value,
                                    "EDIT REJECTED", str(safety["reason"]), experiment_id, safety)
            raise ValueError(f"Safety Policy rejected edit: {safety['reason']}")
        self.store.update_experiment(experiment_id, parameters=merged, safety=safety["risk"])
        proposal = {**decision["proposal"], "parameters": merged}
        self.store.update_decision(decision["id"], proposal=proposal, risk=str(safety["risk"]),
                                   reason=f"Human-edited proposal: {experiment['purpose']}")
        self.store.append_event(experiment["research_id"], EventKind.HUMAN.value,
                                "PARAMETERS EDITED", f"Pending proposal updated to {merged}.",
                                experiment_id, {"decision_id": decision["id"], "safety": safety})
        return self.get_experiment(experiment_id)

    def reject_decision(self, decision_id: str) -> dict[str, Any]:
        decision = self._require_decision(decision_id)
        self.store.resolve_decision(decision_id, "REJECTED")
        if decision["experiment_id"]:
            self.store.update_experiment(decision["experiment_id"], status="CANCELLED")
        self.store.append_event(decision["research_id"], EventKind.HUMAN.value,
                                "HUMAN REJECTION", f"Rejected {decision['intent']}.",
                                decision.get("experiment_id"), {"decision_id": decision_id})
        return self._require_decision(decision_id)

    def execute_command(self, research_id: str, text: str,
                        selected_experiment: str | None = None) -> WorkspaceCommandResult:
        text = text.strip()
        if not text:
            return WorkspaceCommandResult(ok=False, message="Command is empty")
        self._require_research(research_id)
        if not text.startswith("/"):
            self.store.append_event(research_id, EventKind.USER.value, "USER", text)
            self.store.update_research(research_id, current_question=text)
            answer = self._answer_question(research_id, text, selected_experiment)
            self.store.append_event(research_id, EventKind.ANALYSIS.value, "TOPOPTPILOT", answer)
            return WorkspaceCommandResult(ok=True, message=answer, action="message")
        parts = text.split()
        command, args = parts[0].lower(), parts[1:]
        handlers = {
            "/run": lambda: self._command_run(research_id, selected_experiment),
            "/pause": lambda: self._set_research_status(research_id, "PAUSED"),
            "/resume": lambda: self._set_research_status(research_id, "READY"),
            "/stop": lambda: self._command_stop(research_id),
            "/approve": lambda: self._command_decision(research_id, True),
            "/reject": lambda: self._command_decision(research_id, False),
            "/rollback": lambda: self._command_rollback(research_id, args),
            "/compare": lambda: self._command_compare(research_id, args),
            "/lock": lambda: self._command_lock(research_id, args),
            "/unlock": lambda: self._command_unlock(research_id, args),
            "/promote": lambda: self._command_promote(research_id, args),
            "/retry": lambda: self._command_retry(research_id, args),
            "/report": lambda: self._command_report(research_id),
            "/export": lambda: self._command_export(research_id),
        }
        if command in {"/edit"}:
            return WorkspaceCommandResult(ok=True, message="Experiment editor opened.", action="edit")
        if command not in handlers:
            return WorkspaceCommandResult(ok=False, message=f"Unknown command: {command}")
        try:
            return handlers[command]()
        except (KeyError, ValueError) as exc:
            return WorkspaceCommandResult(ok=False, message=str(exc))

    def _command_run(self, research_id: str, selected: str | None) -> WorkspaceCommandResult:
        experiments = self.store.list_experiments(research_id)
        target = self.store.get_experiment(selected) if selected else next(
            (e for e in reversed(experiments) if e["status"] == "WAITING"), None)
        if not target:
            raise ValueError("No waiting experiment is selected")
        self.run_experiment(target["id"])
        return WorkspaceCommandResult(ok=True, message=f"{target['id']} submitted.", action="run",
                                      data={"experiment_id": target["id"]})

    def _set_research_status(self, research_id: str, status: str) -> WorkspaceCommandResult:
        self.store.update_research(research_id, status=status)
        self.store.append_event(research_id, EventKind.SYSTEM.value, status, f"Research is now {status}.")
        return WorkspaceCommandResult(ok=True, message=f"Research {status.lower()}.", action=status.lower())

    def _command_stop(self, research_id: str) -> WorkspaceCommandResult:
        for experiment in self.store.list_experiments(research_id):
            if experiment["status"] in {"WAITING", "RUNNING"} and experiment["run_id"]:
                self.queue.cancel(experiment["run_id"])
                self.store.update_experiment(experiment["id"], status="CANCELLED")
        return self._set_research_status(research_id, "STOPPED")

    def _pending_decision(self, research_id: str) -> dict[str, Any]:
        decision = next((d for d in reversed(self.store.list_decisions(research_id))
                         if d["status"] == "PENDING"), None)
        if not decision:
            raise ValueError("There is no pending decision")
        return decision

    def _command_decision(self, research_id: str, approve: bool) -> WorkspaceCommandResult:
        decision = self._pending_decision(research_id)
        if approve:
            self.approve_decision(decision["id"])
        else:
            self.reject_decision(decision["id"])
        verb = "approved" if approve else "rejected"
        return WorkspaceCommandResult(ok=True, message=f"Decision {decision['id']} {verb}.",
                                      action=verb, data={"decision_id": decision["id"]})

    def _command_compare(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        if len(args) != 2:
            raise ValueError("Usage: /compare <A> <B>")
        experiments = [self.store.get_experiment(item.upper()) for item in args]
        if any(not e or e["research_id"] != research_id for e in experiments):
            raise ValueError("Both experiments must exist in the current research")
        return WorkspaceCommandResult(ok=True, message=f"Comparing {args[0]} and {args[1]}.",
                                      action="compare", data={"experiments": [a.upper() for a in args]})

    def _command_lock(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        if len(args) != 2:
            raise ValueError("Usage: /lock <parameter> <value>")
        research = self._require_research(research_id)
        locks = dict(research["locks"])
        locks[args[0]] = _parse_scalar(args[1])
        self.store.set_locks(research_id, locks)
        return WorkspaceCommandResult(ok=True, message=f"Locked {args[0]}={locks[args[0]]}.", action="lock")

    def _command_unlock(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        if len(args) != 1:
            raise ValueError("Usage: /unlock <parameter>")
        research = self._require_research(research_id)
        locks = dict(research["locks"])
        locks.pop(args[0], None)
        self.store.set_locks(research_id, locks)
        return WorkspaceCommandResult(ok=True, message=f"Unlocked {args[0]}.", action="unlock")

    def _command_rollback(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        source = self._experiment_arg(research_id, args, "/rollback <experiment>")
        clone = ExperimentCreate(purpose=f"Rollback from {source['id']}", fidelity=source["fidelity"],
                                 mesh_level=source["mesh_level"], backend=source["backend"],
                                 parameters=source["parameters"], warm_start=source["id"])
        new = self.create_experiment(research_id, clone)
        return WorkspaceCommandResult(ok=True, message=f"Created {new['id']} from {source['id']}.",
                                      action="select", data={"experiment_id": new["id"]})

    def _command_promote(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        source = self._experiment_arg(research_id, args, "/promote <experiment>")
        current = str(source["fidelity"]).split()[0]
        target = FidelityManager().promote_code(current)
        labels = {"F0": "F0 — 2D Coarse", "F1": "F1 — 2D Fine",
                  "F2": "F2 — Python 3D", "F3": "F3 — MATLAB 3D"}
        promoted = ExperimentCreate(purpose=f"Promote {source['id']} to {target}",
                                    fidelity=labels[target], mesh_level=FidelityManager.mesh_level(target),
                                    backend=FidelityManager.backend_for(target), parameters=source["parameters"],
                                    warm_start=source["id"], requires_approval=target in {"F2", "F3"},
                                    intent="UPGRADE_FIDELITY")
        new = self.create_experiment(research_id, promoted)
        return WorkspaceCommandResult(ok=True, message=f"Created promoted run {new['id']}.",
                                      action="select", data={"experiment_id": new["id"]})

    def _command_retry(self, research_id: str, args: list[str]) -> WorkspaceCommandResult:
        source = self._experiment_arg(research_id, args, "/retry <experiment>")
        if source["status"] != "FAILED":
            raise ValueError("Only failed experiments can be retried")
        self.store.update_experiment(source["id"], status="WAITING", error=None)
        self.run_experiment(source["id"])
        return WorkspaceCommandResult(ok=True, message=f"Retrying {source['id']}.", action="run")

    def _experiment_arg(self, research_id: str, args: list[str], usage: str) -> dict[str, Any]:
        if len(args) != 1:
            raise ValueError(f"Usage: {usage}")
        experiment = self.store.get_experiment(args[0].upper())
        if not experiment or experiment["research_id"] != research_id:
            raise ValueError(f"Experiment {args[0]} does not exist")
        return experiment

    def _command_report(self, research_id: str) -> WorkspaceCommandResult:
        path = self.generate_report(research_id)
        return WorkspaceCommandResult(ok=True, message=f"Report generated: {path}", action="report",
                                      data={"path": str(path)})

    def _command_export(self, research_id: str) -> WorkspaceCommandResult:
        report = self.generate_report(research_id)
        export_dir = self.data_dir / research_id / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        target = export_dir / f"{research_id}_reproduction.zip"
        research_json = json.dumps(self.get_research(research_id), ensure_ascii=False,
                                   indent=2, default=str)
        manifest = {
            "research_id": research_id, "python": platform.python_version(),
            "model": self.agent_client.model, "framework": "official-pi-rpc",
            "research_sha256": hashlib.sha256(research_json.encode("utf-8")).hexdigest(),
        }
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(report, "report.md")
            archive.writestr("research.json", research_json)
            archive.writestr("proposals.json", json.dumps(self.store.list_proposals(research_id),
                                                            ensure_ascii=False, indent=2, default=str))
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("REPRODUCE.md", "# Reproduce\n\n1. `npm ci`\n2. `pip install -r requirements.txt`\n"
                             "3. `python -m topoptpilot.replay research.json --output replay_result.json`\n\n"
                             "Set `DASHSCOPE_API_KEY` only when replaying Pi decisions; FEM replay needs no LLM.\n")
            archive.write(self.project_root / "AGENTS.md", "AGENTS.md")
            archive.write(self.project_root / ".pi/models.example.json", "pi/models.example.json")
            archive.write(self.project_root / "requirements.txt", "requirements.txt")
            archive.write(self.project_root / "package-lock.json", "package-lock.json")
            for case_path in (self.project_root / "topoptpilot/cases").glob("*.json"):
                archive.write(case_path, f"cases/{case_path.name}")
        return WorkspaceCommandResult(ok=True, message=f"Reproduction bundle: {target}", action="export",
                                      data={"path": str(target)})

    def generate_report(self, research_id: str) -> Path:
        research = self.get_research(research_id)
        report_dir = self.data_dir / research_id / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "report.md"
        memory = self.tools.memory.build(research, research["experiments"], research["events"],
                                         research["decisions"])
        budget = FidelityManager.budget(research, research["experiments"])
        zh = research.get("locale", "zh-CN") == "zh-CN"
        headings = ({"title": "TopOptPilot 科研报告", "goal": "研究目标", "constraints": "约束条件",
                     "experiments": "实验", "decisions": "决策", "hypothesis": "假设与证据",
                     "failures": "已知失败", "pareto": "Pareto 候选", "budget": "预算与终止",
                     "repro": "可复现性", "none": "未指定。"} if zh else
                    {"title": "TopOptPilot Research Report", "goal": "Goal", "constraints": "Constraints",
                     "experiments": "Experiments", "decisions": "Decisions", "hypothesis": "Hypothesis and evidence",
                     "failures": "Known failures", "pareto": "Pareto candidates", "budget": "Budget and termination",
                     "repro": "Reproducibility", "none": "Not specified."})
        lines = [f"# {headings['title']} — {research_id}", "", f"## {headings['goal']}", "", research["goal"],
                 "", f"## {headings['constraints']}", "", "```json",
                 json.dumps(research["constraints"], ensure_ascii=False, indent=2), "```", "",
                 f"## {headings['experiments']}", ""]
        for experiment in research["experiments"]:
            metrics = (experiment.get("result") or {}).get("quality", {})
            objective = (experiment.get("result") or {}).get("objective", {})
            lines.append(f"- {experiment['id']} · {experiment['status']} · "
                         f"compliance={objective.get('compliance', '—')} · "
                         f"gray={metrics.get('gray_ratio', '—')} · "
                         f"components={metrics.get('connected_components', '—')}")
        lines.extend(["", f"## {headings['decisions']}", ""])
        for decision in research["decisions"]:
            lines.append(f"- {decision['id']} · {decision['status']} · {decision['intent']}: {decision['reason']}")
        lines.extend(["", f"## {headings['hypothesis']}", "", research.get("hypothesis") or headings["none"],
                      "", f"## {headings['failures']}", "", "```json",
                      json.dumps(memory["L3"]["known_failures"], ensure_ascii=False, indent=2), "```",
                      "", f"## {headings['pareto']}", "", "```json",
                      json.dumps(memory["L2"]["pareto_candidates"], ensure_ascii=False, indent=2), "```",
                      "", f"## {headings['budget']}", "", "```json",
                      json.dumps({"budget": budget, "termination_reason": research.get("termination_reason")},
                                 ensure_ascii=False, indent=2), "```",
                      "", f"## {headings['repro']}", "",
                      f"- Agent runtime: official Pi JSON-RPC / {self.agent_client.model}",
                      "- Solver outputs are deterministic FEM evidence; cached results are content-addressed.",
                      "- Parameter proposals are compiled by Safety Policy from scientific intent."])
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.store.append_event(research_id, EventKind.SYSTEM.value, "REPORT GENERATED", str(path))
        return path

    def compare(self, research_id: str, experiment_ids: list[str]) -> list[dict[str, Any]]:
        values = []
        for experiment_id in experiment_ids:
            experiment = self.get_experiment(experiment_id)
            if experiment["research_id"] != research_id:
                raise ValueError("Experiment belongs to another research")
            values.append(experiment)
        return values

    def matlab_health(self) -> dict[str, Any]:
        return self.matlab_worker.health()

    def restart_matlab(self) -> dict[str, Any]:
        return self.matlab_worker.restart()

    def _answer_question(self, research_id: str, text: str, selected: str | None) -> str:
        research = self._require_research(research_id)
        zh = research.get("locale", "zh-CN") == "zh-CN"
        language = "Simplified Chinese" if zh else "English"
        if self.pi_runtime and self.pi_runtime.health()["available"]:
            context = self.tools.research_get_context(research_id)
            message = (
                "First use research_get_context to refresh authoritative state. Answer the researcher "
                f"in concise {language}, grounded only in tool evidence; separate observations from hypotheses.\n\n"
                f"Current L3 context: {json.dumps(context, ensure_ascii=False, default=str)}\n\n"
                f"Researcher message: {text}"
            )
            threading.Thread(target=self.pi_runtime.send,
                             args=(research_id, message, "causal-reasoning"), daemon=True).start()
            return ("已发送给常驻 Pi Research Agent；流式回复会出现在研究时间线中。" if zh else
                    "Sent to the persistent Pi Research Agent; streaming output will appear in the timeline.")
        experiment = self.store.get_experiment(selected) if selected else None
        evidence = {
            "research_id": research_id,
            "goal": research["goal"],
            "constraints": research["constraints"],
            "selected_experiment": None,
        }
        if experiment:
            evidence["selected_experiment"] = {
                "id": experiment["id"], "status": experiment["status"],
                "parameters": experiment["parameters"],
                "objective": (experiment.get("result") or {}).get("objective", {}),
                "quality": (experiment.get("result") or {}).get("quality", {}),
            }
        response = self.agent_client.chat([
            {"role": "system", "content": (
                f"You are TopOptPilot's research analyst running on PiAgent. Answer in concise {language}. "
                "Use only the supplied research evidence. Distinguish observations from hypotheses, "
                "recommend at most one next experiment, and never reveal chain-of-thought."
            )},
            {"role": "user", "content": (
                f"Research evidence:\n{json.dumps(evidence, ensure_ascii=False, default=str)}\n\n"
                f"Researcher question:\n{text}"
            )},
        ], temperature=0.2, max_tokens=1200)
        if response["success"]:
            return response["content"]
        return self._fallback_answer(experiment)

    @staticmethod
    def _fallback_answer(experiment: dict[str, Any] | None) -> str:
        if experiment and experiment["result"]:
            q = experiment["result"].get("quality", {})
            if q.get("connected_components", 1) != 1:
                return (f"{experiment['id']} has {q.get('connected_components')} connected components. "
                        "The evidence points to aggressive projection relative to the filter radius. "
                        "A lower beta or larger rmin is the next discriminating experiment.")
            return (f"{experiment['id']} is connected. Its gray ratio is "
                    f"{q.get('gray_ratio', 'unknown')}; use /compare to test a causal parameter change.")
        return ("I recorded the question in the research stream. Select a completed experiment for an "
                "evidence-grounded explanation, or create and approve a new proposal.")

    def bootstrap_demo(self) -> dict[str, Any]:
        existing = self.list_research()
        if existing:
            return self.get_research(existing[0]["id"])
        research = self.create_research(ResearchCreate(name="MBB Beam Workspace"))
        self.create_experiment(research["id"], ExperimentCreate(
            purpose="Establish the coarse 2D baseline.", parameters={
                "volfrac": 0.4, "rmin": 1.5, "penal": 3, "beta": 1, "max_iter": 60,
            }))
        return self.get_research(research["id"])

    def _require_research(self, research_id: str) -> dict[str, Any]:
        research = self.store.get_research(research_id)
        if not research:
            raise KeyError(f"Research {research_id} does not exist")
        return research

    def _require_decision(self, decision_id: str) -> dict[str, Any]:
        decision = self.store.get_decision(decision_id)
        if not decision:
            raise KeyError(f"Decision {decision_id} does not exist")
        return decision

    def close(self) -> None:
        if self.pi_runtime:
            self.pi_runtime.close()
        self.queue.shutdown(wait=True)
        self.matlab_worker.close()


def _parse_scalar(value: str) -> Any:
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    try:
        return float(value)
    except ValueError:
        return value
