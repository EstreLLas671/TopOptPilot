"""Single application service shared by the Workspace and the test API."""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
import hashlib
import platform
import copy
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from topoptpilot.executor import ExperimentQueue
from topoptpilot.executor.cache import ResultCache
from topoptpilot.executor.executor import build_solver_task
from topoptpilot.memory import ResearchStateStore
from topoptpilot.memory.research_state import utc_now
from topoptpilot.knowledge import KnowledgeBase
from topoptpilot.fidelity import FidelityManager
from topoptpilot.orchestrator import ResearchOrchestrator
from solver.result_schema import connected_components, gray_ratio as density_gray_ratio
from topoptpilot.policy.approval_policy import requires_human_approval
from topoptpilot.schemas import (
    DecisionStatus, EventKind, ExperimentCreate, ExperimentStatus,
    ResearchCreate, WorkspaceCommandResult,
)
from topoptpilot.schemas.models import AppSettings
from topoptpilot.tools import ResearchTools
from topoptpilot.agent_runtime import PiBridge
from topoptpilot.reports import ResearchReportGenerator
from topoptpilot.nomenclature import normalize_mode, normalize_stage, stage_label
from topoptpilot.version import __version__
from topoptpilot.security import (delete_qwen_api_key, get_qwen_api_key,
                                  qwen_api_key_source, set_qwen_api_key)
from agent.llm.client import PiAgentClient
from mcp.matlab_mcp import MatlabMcpError, MatlabMcpWorker


STATUS_SYMBOLS = {
    "WAITING": "○", "RUNNING": "▶", "SUCCESS": "✓",
    "FAILED": "✗", "CANCELLED": "⚠",
}

DEFAULT_APP_SETTINGS = AppSettings().model_dump()


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


_SURFACE_CUBE_VERTICES = (
    (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
    (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
)
_SURFACE_TETRAHEDRA = (
    (0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6),
    (0, 3, 7, 6), (0, 7, 4, 6), (0, 4, 5, 6),
)
_SURFACE_TETRA_EDGES = ((0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 3))


def _density_surface_triangles(density: Any, dimensions: list[float] | tuple[float, ...] | None,
                               level: float = .5) -> list[list[tuple[float, float, float]]]:
    """Extract a display-only smooth isosurface without voxel or element edges."""
    import numpy as np
    from scipy.ndimage import gaussian_filter

    values = np.asarray(density, dtype=float)
    if values.ndim != 3 or min(values.shape) < 1 or not np.isfinite(values).all():
        return []
    # A small display-only interpolation removes staircase seams while keeping
    # the source F3 density array and its resolution untouched as evidence.
    scalar = gaussian_filter(np.pad(values, 1, mode="constant"), sigma=.35)
    rows, columns, layers = values.shape
    physical = [float(value) for value in (dimensions or [columns, rows, layers])[:3]]
    while len(physical) < 3:
        physical.append(1.0)

    def physical_point(row: float, column: float, layer: float) -> tuple[float, float, float]:
        return (
            min(max((column - .5) / max(columns, 1), 0.0), 1.0) * physical[0],
            min(max((row - .5) / max(rows, 1), 0.0), 1.0) * physical[1],
            min(max((layer - .5) / max(layers, 1), 0.0), 1.0) * physical[2],
        )

    triangles: list[list[tuple[float, float, float]]] = []
    padded_rows, padded_columns, padded_layers = scalar.shape
    for layer in range(padded_layers - 1):
        for column in range(padded_columns - 1):
            for row in range(padded_rows - 1):
                cube = [
                    ((row + dr, column + dc, layer + dl), scalar[row + dr, column + dc, layer + dl])
                    for dr, dc, dl in _SURFACE_CUBE_VERTICES
                ]
                for tetrahedron in _SURFACE_TETRAHEDRA:
                    tetra = [cube[index] for index in tetrahedron]
                    intersections: list[tuple[float, float, float]] = []
                    for left_index, right_index in _SURFACE_TETRA_EDGES:
                        left_point, left_value = tetra[left_index]
                        right_point, right_value = tetra[right_index]
                        if (left_value >= level) == (right_value >= level):
                            continue
                        amount = (level - left_value) / (right_value - left_value)
                        point = tuple(
                            left_point[index] + (right_point[index] - left_point[index]) * amount
                            for index in range(3)
                        )
                        intersections.append(physical_point(*point))
                    if len(intersections) == 3:
                        triangles.append(intersections)
                    elif len(intersections) == 4:
                        triangles.extend((intersections[:3], [intersections[0], intersections[2], intersections[3]]))
    return triangles


def _validate_writable_dir(raw: str | None) -> Path | None:
    """Return the resolved absolute path of an existing writable directory, or None."""
    if raw is None or not str(raw).strip():
        return None
    candidate = Path(str(raw).strip()).expanduser().resolve()
    if not candidate.is_dir() or not os.access(candidate, os.W_OK):
        raise ValueError("Directory must exist and be writable")
    return candidate

def _validate_fidelity_backend(fidelity: str, backend: str) -> str:
    value = str(backend)
    if value == "simulate":
        raise ValueError("backend=simulate is forbidden for formal experiments")
    code = normalize_stage(fidelity)
    try:
        expected = FidelityManager.backend_for(code)
    except (KeyError, ValueError) as exc:
        raise ValueError("fidelity must start with Step1, Step2, Step3, or Step4") from exc
    if value != expected:
        raise ValueError(
            f"{code} requires backend={expected}; received backend={value}"
        )
    return code


class ResearchService:
    def __init__(self, data_dir: str | Path | None = None, max_workers: int = 2,
                 agent_client: PiAgentClient | None = None,
                 enable_agent_runtime: bool = True):
        configured_data = data_dir or os.environ.get("TOPOPTPILOT_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
        if not configured_data:
            configured_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TopOptPilot"
        self.data_dir = Path(configured_data).resolve()
        self.project_root = Path(os.environ.get(
            "TOPPILOT_RESOURCE_ROOT", Path(__file__).resolve().parents[2])).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = ResearchStateStore(self.data_dir / "research.db")
        self.knowledge = KnowledgeBase(self.store, self.project_root / "topoptpilot/knowledge/documents")
        self.queue = ExperimentQueue(self.data_dir / "progress", max_workers=max_workers)
        self._matlab_eng_cancels: dict[str, threading.Event] = {}
        self.matlab_worker = MatlabMcpWorker(self.data_dir, self.project_root)
        self._autonomous_stop_lock = threading.RLock()
        self._cache_dir_lock = threading.RLock()
        self.cache_dir = self._resolve_cache_dir(
            (self.store.get_app_settings() or {}).get("data", {}).get("cache_dir"))
        self.cache = ResultCache(self.cache_dir)
        self.report_generator = ResearchReportGenerator(self.data_dir)
        self.orchestrator = ResearchOrchestrator()
        self.agent_client = agent_client or PiAgentClient(api_key=get_qwen_api_key())
        self.tools = ResearchTools(self)
        self.pi_runtime = None
        self.pi_runtime_error = None
        if enable_agent_runtime:
            try:
                self.pi_runtime = PiBridge(self)
            except Exception as exc:
                self.pi_runtime_error = str(exc)
        else:
            self.pi_runtime_error = "disabled"
        self._completion_lock = threading.RLock()
        self._experiment_creation_lock = threading.RLock()
        self._matlab_restart = {"running": False, "last_error": None, "updated_at": None}
        self._qwen_validation = {"status": "CONFIGURED" if get_qwen_api_key()
                                 else "NOT_CONFIGURED", "checked_at": None, "error": None}
        # Keep one stable lock per touched experiment for the service lifetime.
        # Replacing terminal locks can recreate the race this table prevents.
        self._experiment_locks_guard = threading.Lock()
        self._experiment_locks: dict[str, threading.RLock] = {}

    def get_settings(self) -> dict[str, Any]:
        persisted = self.store.get_app_settings() or {}
        updated_at = persisted.pop("updated_at", None)
        settings = AppSettings.model_validate(_deep_merge(DEFAULT_APP_SETTINGS, persisted)).model_dump()
        settings["api_key_status"] = qwen_api_key_source()
        settings["updated_at"] = updated_at
        return settings

    @staticmethod
    def agent_api_key() -> str:
        """Return the runtime credential without serializing or logging it."""
        return get_qwen_api_key()

    def _resolve_cache_dir(self, configured: str | None) -> Path:
        """Resolve the active cache directory, falling back to <data_dir>/cache."""
        default = (self.data_dir / "cache").resolve()
        try:
            target = _validate_writable_dir(configured)
        except (ValueError, OSError):
            target = None
        if target is None or target == self.data_dir:
            return default
        return target

    def _migrate_cache_dir(self, old_dir: Path, new_dir: Path) -> dict[str, Any]:
        """Move every cache entry from old_dir into new_dir, rolling back on failure."""
        moved, skipped = 0, 0
        relocated: list[tuple[Path, Path]] = []
        with self._cache_dir_lock:
            new_dir.mkdir(parents=True, exist_ok=True)
            try:
                for item in sorted(old_dir.iterdir()) if old_dir.exists() else []:
                    destination = new_dir / item.name
                    if destination.exists():
                        skipped += 1
                        continue
                    shutil.move(str(item), str(destination))
                    relocated.append((destination, item))
                    moved += 1
            except OSError as exc:
                for destination, origin in reversed(relocated):
                    try:
                        shutil.move(str(destination), str(origin))
                    except OSError:
                        pass
                raise ValueError(f"Cache migration failed and was rolled back: {exc}") from exc
            self.cache_dir = new_dir
            self.cache = ResultCache(new_dir)
            try:
                if old_dir.exists() and not any(old_dir.iterdir()) and old_dir != new_dir:
                    old_dir.rmdir()
            except OSError:
                pass
        return {"moved_files": moved, "skipped_existing": skipped,
                "cache_dir": str(new_dir)}

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("Settings patch must be an object")
        forbidden = {"api_key", "apiKey", "DASHSCOPE_API_KEY", "key", "secret", "token"}
        if any(key in forbidden for key in patch):
            raise ValueError("API keys must use the dedicated Windows Credential Manager endpoint")
        current = self.get_settings()
        current.pop("api_key_status", None)
        current.pop("updated_at", None)
        merged = AppSettings.model_validate(_deep_merge(current, patch)).model_dump()
        from urllib.parse import urlparse
        endpoint = urlparse(merged["agent"]["base_url"].strip())
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("Agent Base URL must be an absolute HTTP(S) URL")
        merged["agent"]["base_url"] = merged["agent"]["base_url"].rstrip("/")
        matlab_root = merged["compute"].get("matlab_root")
        if matlab_root:
            candidate = Path(matlab_root).expanduser().resolve()
            executable = candidate / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")
            if not candidate.is_dir() or not executable.is_file():
                raise ValueError("MATLAB root must be an existing installation containing bin/matlab")
            merged["compute"]["matlab_root"] = str(candidate)
        requested_root = merged["data"].get("next_data_dir")
        if requested_root:
            target = _validate_writable_dir(requested_root)
            merged["data"]["next_data_dir"] = str(target)
        requested_cache = merged["data"].get("cache_dir")
        if requested_cache is not None and not str(requested_cache).strip():
            requested_cache = None
        if requested_cache is not None:
            # Reuse the writable-directory rule so a typo cannot orphan the cache.
            cache_target = _validate_writable_dir(str(requested_cache))
            if cache_target == self.data_dir:
                raise ValueError("Cache directory must be a dedicated directory, not the data root")
            merged["data"]["cache_dir"] = str(cache_target)
        else:
            merged["data"]["cache_dir"] = None
        cache_migration = None
        desired_cache = self._resolve_cache_dir(merged["data"]["cache_dir"])
        if desired_cache != self.cache_dir:
            cache_migration = self._migrate_cache_dir(self.cache_dir, desired_cache)
        root_changed = merged["compute"]["matlab_root"] != current["compute"]["matlab_root"]
        self.store.save_app_settings(merged)
        # The bootstrap mirror contains only the delayed data-root selector; all normal
        # preferences remain in SQLite and no secrets are ever copied here.
        bootstrap = os.getenv("TOPPILOT_BOOTSTRAP_PATH")
        if bootstrap:
            Path(bootstrap).parent.mkdir(parents=True, exist_ok=True)
            Path(bootstrap).write_text(json.dumps({"next_data_dir": merged["data"]["next_data_dir"]}, ensure_ascii=False), encoding="utf-8")
        if root_changed:
            # Restart/probe off the FastAPI thread so a cold MATLAB launch never
            # freezes the Tauri Workspace.
            self.restart_matlab()
        result = self.get_settings()
        if cache_migration:
            result["data"]["cache_migration"] = cache_migration
        return result

    def restart_pi(self) -> dict[str, Any]:
        if not self.pi_runtime:
            raise RuntimeError(self.pi_runtime_error or "Pi runtime is unavailable")
        self.pi_runtime.close()
        self.pi_runtime = PiBridge(self)
        return self.pi_runtime.health()

    def set_agent_key(self, api_key: str) -> dict[str, Any]:
        set_qwen_api_key(api_key)
        self.agent_client.update_config(api_key=get_qwen_api_key())
        self._qwen_validation = {"status": "CONFIGURED", "checked_at": None, "error": None}
        return {"configured": True, "source": qwen_api_key_source()}

    def delete_agent_key(self) -> dict[str, Any]:
        deleted = delete_qwen_api_key()
        self.agent_client.api_key = os.getenv("DASHSCOPE_API_KEY", "")
        self._qwen_validation = {"status": "CONFIGURED" if self.agent_client.api_key else "NOT_CONFIGURED",
                                 "checked_at": None, "error": None}
        return {"deleted": deleted, "source": qwen_api_key_source()}
    def test_agent_settings(self) -> dict[str, Any]:
        settings = self.get_settings()["agent"]
        key = get_qwen_api_key()
        if not key:
            return {"ok": False, "status": "not_configured", "model": settings["model"]}
        # The credential remains in memory only for this connection attempt.
        old_model, old_base, old_key = self.agent_client.model, self.agent_client.base_url, self.agent_client.api_key
        self.agent_client.model = settings["model"]
        self.agent_client.base_url = settings["base_url"]
        self.agent_client.api_key = key
        try:
            response = self.agent_client.chat(
                [{"role": "user", "content": "Reply SETTINGS_CONNECTION_OK."}],
                temperature=0, max_tokens=16)
            if not response.get("success"):
                raise RuntimeError(response.get("error") or "Qwen API returned a degraded response")
            self._qwen_validation = {"status": "VERIFIED", "checked_at": utc_now(), "error": None}
            return {"ok": True, "status": "verified", "model": settings["model"]}
        except Exception as exc:
            self._qwen_validation = {"status": "FAILED", "checked_at": utc_now(),
                                     "error": str(exc)[:500]}
            return {"ok": False, "status": "failed", "model": settings["model"], "error": str(exc)[:500]}
        finally:
            self.agent_client.model, self.agent_client.base_url, self.agent_client.api_key = old_model, old_base, old_key

    def diagnostics(self) -> dict[str, Any]:
        def directory_size(path: Path) -> int:
            return sum(item.stat().st_size for item in path.rglob("*") if item.is_file()) if path.exists() else 0
        disk = shutil.disk_usage(self.data_dir)
        return {"health": self.health(), "data_dir": str(self.data_dir),
                "database": str(self.store.db_path), "cache_dir": str(self.cache_dir),
                "cache_bytes": directory_size(self.cache_dir),
                "log_dir": str(self.data_dir / "logs"), "free_disk_bytes": disk.free,
                "sidecar_port": os.getenv("TOPPILOT_SIDECAR_PORT"), "version": __version__}

    def export_diagnostics(self) -> Path:
        output = self.data_dir / "diagnostics" / f"topoptpilot-diagnostics-{uuid.uuid4().hex[:8]}.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("diagnostics.json", json.dumps(self.diagnostics(), ensure_ascii=False, indent=2, default=str))
            archive.writestr("settings.json", json.dumps(self.get_settings(), ensure_ascii=False, indent=2))
        return output

    def clear_regenerable_cache(self) -> dict[str, Any]:
        removed = 0
        for directory in (self.cache_dir, self.data_dir / "progress"):
            if not directory.exists():
                continue
            resolved = directory.resolve()
            # Progress always lives under data_dir; the cache may be a custom
            # directory chosen in Settings, which is only clearable as a whole.
            if resolved != self.cache_dir.resolve() and self.data_dir not in resolved.parents:
                continue
            for item in directory.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
                removed += 1
        return {"removed_entries": removed, "message": "Only regenerable cache and progress files were removed."}

    def health(self) -> dict[str, Any]:
        runtime = (self.pi_runtime.health() if self.pi_runtime else
                   {"available": False, "status": "unavailable", "last_error": self.pi_runtime_error})
        matlab_mcp = self.matlab_worker.health()
        pi_status = "READY" if runtime.get("available") else "FAILED"
        raw_mcp_state = str(matlab_mcp.get("state", "UNAVAILABLE"))
        mcp_state = "CONFIGURED" if raw_mcp_state == "AVAILABLE" else raw_mcp_state
        matlab_state = ("VERIFIED" if mcp_state == "READY" else
                        "CONFIGURED" if mcp_state == "CONFIGURED" else "NOT_CONFIGURED")
        components = {
            "pi_rpc": {"status": pi_status, "runtime": "Pi Agent RPC",
                       "model": runtime.get("model"), "last_error": runtime.get("last_error")},
            "qwen_api": {**self._qwen_validation, "provider": "dashscope",
                         "model": self.get_settings()["agent"]["model"]},
            "matlab_2d": {"status": matlab_state, "backend": "MATLAB MCP", "steps": "Step1/Step2"},
            "matlab_3d": {"status": matlab_state, "backend": "MATLAB MCP", "steps": "Step3/Step4"},
            "python_dev": {"status": "CONFIGURED", "backend": "development regression only"},
            # Kept for V5 diagnostics consumers only; the V6 Workspace does not
            # present these as formal experiment backends.
            "python_2d": {"status": "READY", "backend": "development regression only", "formal": False},
            "python_3d": {"status": "READY", "backend": "development regression only", "formal": False},
            "matlab_mcp": {"status": mcp_state, **matlab_mcp},
            "matlab": {"status": matlab_state, "version": matlab_mcp.get("matlab_version"),
                       "root": matlab_mcp.get("matlab_root")},
            "sidecar": {"status": "VERIFIED", "port": os.getenv("TOPPILOT_SIDECAR_PORT"),
                        "version": __version__},
        }
        return {"status": "ok", "version": __version__, "components": components,
                "solver_2d": matlab_state in {"READY", "VERIFIED"}, "solver_3d": matlab_state in {"READY", "VERIFIED"},
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
        if isinstance(request, ResearchCreate):
            model, inherited = request, {}
        else:
            defaults = self.get_settings()["new_research"]
            inherited = {"defaults": {"experiment": defaults["experiment"]}}
            seed = {"mode": defaults["mode"], "budget_total": defaults["budget_total"],
                    "budgets": defaults["budgets"], "constraints": defaults["constraints"],
                    "material": defaults["material"], "locale": self.get_settings()["locale"]}
            model = ResearchCreate.model_validate(_deep_merge(seed, request))
        research_id = self._next_research_id()
        payload = model.model_dump()
        payload["budgets"] = model.normalized_budgets()
        sources = {key: model.field_sources.get(key, "USER" if isinstance(request, dict)
                   and key in request else "DEFAULT") for key in (
                       "name", "goal", "description", "geometry", "material", "loads", "boundary_conditions",
                       "constraints", "mode", "budget_total", "budgets", "hypothesis")}
        contract = {"version": "6.0", "immutable": True, "confirmed_at": utc_now(),
                    "goal": model.goal, "description": model.description, "geometry": model.geometry, "material": model.material,
                    "loads": model.loads, "boundary_conditions": model.boundary_conditions,
                    "constraints": model.constraints, "mode": model.mode,
                    "budget_total": model.budget_total, "budgets": payload["budgets"],
                    "hypothesis": model.hypothesis, "field_sources": sources}
        research = self.store.create_research({"id": research_id, **payload, **inherited,
                                               "contract": contract})
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
        fidelity = str(proposal["fidelity"])
        if normalize_stage(fidelity) == "STEP4" and self.pi_runtime:
            # 独立评审是辅助审计，不是提交门禁：Pi RPC 不可用时记录并继续，
            # 绝不能让评审派发失败阻断 Step4 验证实验的提交。
            try:
                self.pi_runtime.subagents.dispatch(
                    research_id, "INDEPENDENT_REVIEWER",
                    "Audit this Step4 upgrade for evidence sufficiency, controlled comparison and safety. "
                    "Do not submit it.", proposal.get("evidence_ids", []), proposal_id)
            except Exception as dispatch_error:
                self.store.append_event(
                    research_id, EventKind.SYSTEM.value, "INDEPENDENT_REVIEWER_UNAVAILABLE",
                    f"独立评审子代理暂不可用（{dispatch_error}）；Step4 提交继续，"
                    "人工阶段审批仍是唯一门禁。", proposal_id)
        knowledge_ids: list[str] = []
        for event in reversed(self.store.list_events(research_id)):
            for knowledge_id in (event.get("payload") or {}).get("knowledge_ids", []):
                if knowledge_id not in knowledge_ids:
                    knowledge_ids.append(knowledge_id)
            if len(knowledge_ids) >= 8:
                break
        related_tasks = [item["id"] for item in self.store.list_subagent_tasks(research_id)
                         if item.get("proposal_id") == proposal_id][-8:]
        request = ExperimentCreate(
            purpose=proposal["purpose"], fidelity={
                step: stage_label(step) for step in FidelityManager.CODES
            }[normalize_stage(fidelity)], mesh_level=FidelityManager.mesh_level(fidelity),
            backend=proposal["backend"], parameters=proposal["parameters"],
            warm_start=proposal.get("source_experiment"),
            requires_approval=bool(proposal["approval_required"]),
            proposal_id=proposal_id, intent=proposal["intent"],
            decision_source=proposal.get("decision_source", "HUMAN"),
            intent_source=proposal.get("intent_source", "HUMAN"),
            policy_version=proposal.get("policy_version"), model=proposal.get("model"),
            provider=proposal.get("provider"), session_id=proposal.get("session_id"),
            evidence_ids=proposal.get("evidence_ids", []),
            knowledge_ids=knowledge_ids, subagent_task_ids=related_tasks,
        )
        experiment = self.create_experiment(research_id, request)
        self.store.update_proposal(proposal_id, status=(
            "PENDING_HUMAN_APPROVAL" if experiment.get("decision_id") else "SUBMITTED"),
            experiment_id=experiment["id"])
        return {"proposal": self.store.get_proposal(proposal_id),
                "experiment": self.get_experiment(experiment["id"])}

    def start_autonomous_research(self, research_id: str) -> dict[str, Any]:
        """Start (or resume) the deep-optimization loop; every completed step waits for the user's decision."""
        research = self._require_research(research_id)
        if self._pending_fidelity_stage_gate(research_id):
            raise ValueError("当前 Step 结果仍在等待人工审批，请先在弹窗中作出选择")
        status = str(research.get("status") or "").upper()
        if status in {"RUNNING", "STOPPING"}:
            raise ValueError("自主研究仍在运行或停止中")
        if status == "STOP_FAILED":
            raise ValueError("上次停止未完成，请先重试停止自主研究")
        if str(research.get("termination_reason") or "").upper() == "USER_STOPPED":
            self.store.create_next_research_run(research_id)
            research = self._require_research(research_id)
        defaults = dict(research.get("defaults") or {})
        workflow = dict(defaults.get("autonomous_workflow") or {})
        # 存在未消费的 Step 授权时从该 Step 恢复（例如上一轮回退线程异常
        # 中断后遗留的 STEP4 验证授权），而不是把用户硬拽回 Step1。
        existing_authorization = dict(workflow.get("step_authorization") or {})
        existing_ids = [str(item) for item in (existing_authorization.get("experiment_ids") or [])]
        resumable = bool(
            existing_authorization
            and not existing_authorization.get("consumed")
            and not existing_ids
            and normalize_stage(existing_authorization.get("stage")) in {"STEP1", "STEP2", "STEP3", "STEP4"}
            and normalize_stage(workflow.get("active_fidelity") or "") == normalize_stage(existing_authorization.get("stage"))
        )
        if resumable:
            workflow["active_fidelity"] = normalize_stage(existing_authorization.get("stage"))
        else:
            workflow["active_fidelity"] = "STEP1"
            workflow["step_authorization"] = {
                "stage": "STEP1", "source": "START_DEEP_OPTIMIZATION", "consumed": False,
                "candidates_limit": 3, "experiment_ids": [],
                "baseline_experiment_id": None,
            }
        defaults["autonomous_workflow"] = workflow
        self.store.update_research_json(research_id, defaults=defaults)
        self.store.update_research(research_id, mode="DEEP_OPTIMIZATION", status="RUNNING",
                                   termination_reason=None)
        self.store.append_event(research_id, EventKind.SYSTEM.value, "ROUND_STARTED",
                                f"Autonomous round {int(research.get('current_round', 0)) + 1} started.")
        self.store.append_event(
            research_id,
            EventKind.SYSTEM.value,
            "ONE_STEP_RUN_STARTED",
            "本轮将在当前 Step 生成三个不同方向的受控候选（Step4 为单一验证实验）并全部真实求解，完成后立即等待人工选择。",
            payload={"stage": "one_step_one_run", "required_plans": 3},
            source="RESEARCH_ORCHESTRATOR",
        )
        baseline = (research.get("defaults") or {}).get("engineering_scheme_baseline")
        baseline_ids = [value for value in [
            (baseline or {}).get("schemeId"), (baseline or {}).get("runId")
        ] if value]
        self.store.append_event(
            research_id, EventKind.SYSTEM.value, "WORKFLOW_CONTEXT_COMPLETED",
            "已读取研究目标、假设和可用真实基线。",
            payload={
                "workflow_step": "context", "status": "completed",
                "reflection": "优先采用已导入工程方案；其后才使用当前 Research 的真实实验和历史最优结果。",
                "evidence_ids": baseline_ids, "next_action": "生成本轮受控候选方案组",
            },
            source="RESEARCH_ORCHESTRATOR",
        )
        self.store.append_event(
            research_id, EventKind.SYSTEM.value, "WORKFLOW_PLANNING_STARTED",
            "正在生成当前 Step 的受 Policy 约束候选方案组（Step1–Step3 三个方向，Step4 单一验证）。",
            payload={"workflow_step": "planning", "status": "active", "required_plans": 3},
            source="RESEARCH_ORCHESTRATOR",
        )
        language = "Simplified Chinese" if research.get("locale", "zh-CN") == "zh-CN" else "English"
        prompt = (
            "You are the primary Pi Research Agent. Begin at Step1. "
            "First call research_get_context, "
            "solver_get_capabilities and knowledge_search. Dispatch the HYPOTHESIS and "
            "EXPERIMENT_PLANNER Subagents when their bounded review is needed. For the authorized "
            "Step1-Step3 round, propose exactly three different-direction candidate plans against the "
            "same baseline: each candidate may vary only volfrac or one hidden whitelist factor "
            "(beta, beta_max, projection, controller, move), and the three candidates must not repeat "
            "the same controlled factor or intent. Compile every candidate through "
            "policy_compile_intent, keep all of them at the authorized Step, preview and submit all "
            "three. For a Step4 round, propose and submit exactly one verification experiment instead. "
            "Wait for their real FEM evidence, then "
            "select the best route, record a diagnosis of its weaknesses, and formulate the next-round plan. "
            "The authoritative optimization configuration defines geometry, load case, material, grid, "
            "penal, rmin, iteration limits, accuracy and filter strategy. Never change those fields. "
            "Do not invent metrics or provide numeric solver parameters directly. "
            f"After all candidates of this round finish, stop and wait for the explicit human step decision. Reply in {language}."
        )
        threading.Thread(target=self._send_pi_or_fallback,
                         args=(research_id, prompt, "experiment-planning"), daemon=True).start()
        return self.get_research(research_id)

    def stop_autonomous_research(self, research_id: str) -> dict[str, Any]:
        """Stop every active autonomous child and expose STOPPED only after reconciliation."""
        with self._autonomous_stop_lock:
            research = self._require_research(research_id)
            status = str(research.get("status") or "").upper()
            reason = str(research.get("termination_reason") or "").upper()
            if status == "STOPPED" and reason == "USER_STOPPED":
                return self.get_research(research_id)
            if status == "STOPPING":
                return self.get_research(research_id)

            run_ids: list[tuple[str, str]] = []
            for experiment in self.store.list_experiments(research_id):
                experiment_status = str(experiment.get("status") or "").upper()
                if (status == "STOP_FAILED" and experiment_status == "CANCELLED"
                        and experiment.get("run_id")
                        and not str(experiment["run_id"]).startswith("claim_")):
                    run_ids.append((str(experiment["run_id"]), str(experiment.get("backend") or "")))
                if experiment_status in {"WAITING", "QUEUED", "RUNNING", "PENDING"}:
                    if experiment.get("run_id") and not str(experiment["run_id"]).startswith("claim_"):
                        run_ids.append((str(experiment["run_id"]), str(experiment.get("backend") or "")))
                    self.store.update_experiment(
                        experiment["id"], status="CANCELLED", completed_at=utc_now(),
                        error="自主研究已由用户停止",
                    )
            for decision in self.store.list_decisions(research_id):
                if decision.get("status") == "PENDING":
                    self.store.resolve_decision_if_pending(decision["id"], "REJECTED")
            for proposal in self.store.list_proposals(research_id):
                if str(proposal.get("status") or "").upper() in {
                    "PREVIEW", "PENDING", "PENDING_HUMAN_APPROVAL", "SUBMITTED"
                }:
                    self.store.update_proposal(proposal["id"], status="CANCELLED")
            for task in self.store.list_subagent_tasks(research_id):
                if str(task.get("status") or "").upper() in {"QUEUED", "RUNNING", "PENDING"}:
                    self.store.update_subagent_task(
                        task["id"], status="CANCELLED", completed_at=utc_now(),
                        error="自主研究已由用户停止",
                    )
            self.store.update_research(
                research_id, status="STOPPING", termination_reason="USER_STOPPED",
            )
            self.store.append_event(
            research_id, EventKind.HUMAN.value, "DEEP_OPTIMIZATION_STOP_REQUESTED",
                "用户要求停止自主研究；正在终止 Agent、子任务和求解器。",
                payload={"run_ids": [run_id for run_id, _ in run_ids]}, source="USER",
            )
            stopping_response = self.get_research(research_id)

            def reconcile_stop() -> None:
                errors: list[str] = []
                if self.pi_runtime is not None:
                    try:
                        self.pi_runtime.cancel(research_id)
                        self.pi_runtime.release(research_id)
                    except Exception as exc:
                        errors.append(f"Pi: {exc}")
                for run_id, backend in run_ids:
                    try:
                        worker = self.matlab_worker if backend == "matlab" else self.queue
                        worker.cancel(run_id)
                        if not worker.wait_for_stop(run_id, timeout=15.0):
                            errors.append(f"{backend or 'python'}:{run_id} 未在超时内停止")
                    except Exception as exc:
                        errors.append(f"{backend or 'python'}:{run_id}: {exc}")
                try:
                    self.store.upsert_agent_session(
                        research_id, status="OFFLINE", stream_text="",
                        last_error="；".join(errors) if errors else None,
                    )
                    if errors:
                        self.store.update_research(research_id, status="STOP_FAILED")
                        self.store.append_event(
                            research_id, EventKind.SYSTEM.value, "DEEP_OPTIMIZATION_STOP_FAILED",
                            "；".join(errors), payload={"errors": errors},
                        )
                    else:
                        self.store.update_research(
                            research_id, status="STOPPED", termination_reason="USER_STOPPED",
                        )
                        self.store.append_event(
                            research_id, EventKind.SYSTEM.value, "DEEP_OPTIMIZATION_STOPPED",
                            "自主研究后台链路已全部停止；下次运行将建立空白活动轮次。",
                            payload={"termination_reason": "USER_STOPPED"},
                        )
                except Exception:
                    self.store.update_research(research_id, status="STOP_FAILED")

            threading.Thread(
                target=reconcile_stop, daemon=True, name=f"stop-autonomous-{research_id}",
            ).start()
            return stopping_response

    @staticmethod
    def _chinese_reflection(status: str, evaluation: dict[str, Any] | None) -> str:
        """执行进度面板的中文阶段反思：求解有效性 + 目标差距。"""
        if status != "SUCCESS":
            return "求解无效，未产生可用于结论的真实指标。"
        unmet = [str(item) for item in ((evaluation or {}).get("unmet_targets") or [])]
        gap_labels = {"gray": "灰度率高于目标", "connected": "拓扑不连通",
                      "stress": "应力超出参考限值"}
        gaps = "；".join(gap_labels.get(item, item) for item in unmet)
        if gaps:
            return f"求解收敛，指标有效。目标差距：{gaps}；差距将作为后续轮次的优化方向。"
        return "求解收敛，指标有效，已达成全部目标阈值。"

    @staticmethod
    def _select_round_best(successful_items: list[dict[str, Any]]) -> dict[str, Any]:
        """对比本轮候选的连通性、灰度率与柔度，选出最优方案。

        顺序：结构连通优先，灰度率更低次之，柔度更低收尾。
        """
        def rank(item: dict[str, Any]) -> tuple:
            result = item.get("result") or {}
            quality = result.get("quality") or {}
            connected = quality.get("connected_components")
            gray = quality.get("gray_ratio")
            compliance = (result.get("objective") or {}).get("compliance")
            return (0 if connected == 1 else 1,
                    float(gray) if isinstance(gray, (int, float)) else 1.0,
                    float(compliance) if isinstance(compliance, (int, float)) else float("inf"))
        return min(successful_items, key=rank, default=None) or {}

    @staticmethod
    def _has_usable_stage_result(item: dict[str, Any]) -> bool:
        """A screening Step may legally miss the final targets; any real FEM
        metrics from the deterministic evaluator count as usable evidence."""
        if item.get("status") == "SUCCESS" and item.get("result"):
            return True
        objective = (item.get("result") or {}).get("objective") or {}
        compliance = objective.get("compliance")
        return isinstance(compliance, (int, float)) and not isinstance(compliance, bool)

    def _pending_fidelity_stage_gate(self, research_id: str) -> dict[str, Any] | None:
        events = self.store.list_events(research_id)
        resolved = {
            str((event.get("payload") or {}).get("gate_event_id"))
            for event in events if event.get("title") == "FIDELITY_STAGE_DECISION"
        }
        for event in reversed(events):
            if (event.get("title") == "FIDELITY_STAGE_AWAITING_DECISION"
                    and str(event.get("id")) not in resolved):
                return event
        return None

    def decide_fidelity_stage(self, research_id: str, decision: str | bool) -> dict[str, Any]:
        # Gate lookup and consumption must be one critical section; otherwise
        # two windows can both act on the same pending stage event.
        with self._completion_lock:
            return self._decide_fidelity_stage_locked(research_id, decision)

    def _decide_fidelity_stage_locked(self, research_id: str,
                                      decision: str | bool) -> dict[str, Any]:
        research = self._require_research(research_id)
        gate = self._pending_fidelity_stage_gate(research_id)
        if not gate: raise ValueError('当前没有等待确认的保真度阶段结果')
        payload = gate.get('payload') or {}
        stage_code = normalize_stage(payload.get('stage_code') or payload.get('internal_fidelity'))
        action = ('ADVANCE_STAGE' if decision else 'REPEAT_STAGE') if isinstance(decision, bool) else str(decision or '').upper()
        if action not in {'REPEAT_STAGE','ADVANCE_STAGE','APPROVE_FINAL'}: raise ValueError('无效的阶段决策动作')
        rank = {'STEP1':0,'STEP2':1,'STEP3':2,'STEP4':3}
        is_final = stage_code == 'STEP4'
        if action == 'APPROVE_FINAL':
            if not is_final: raise ValueError('当前阶段不是最终阶段')
            ids = set(payload.get('experiment_ids') or [])
            all_experiments = self.store.list_experiments(research_id)
            usable_codes = {normalize_stage(item.get('fidelity'))
                            for item in all_experiments if self._has_usable_stage_result(item)}
            step3_ids = {item['id'] for item in all_experiments
                         if normalize_stage(item.get('fidelity')) == 'STEP3'
                         and self._has_usable_stage_result(item)}
            if not {'STEP1', 'STEP2', 'STEP3', 'STEP4'}.issubset(usable_codes):
                raise ValueError('结束实验前必须完成 Step1、Step2、Step3、Step4 全部真实有效流程')
            successful = [item for item in all_experiments
                          if item.get('status') == 'SUCCESS' and item.get('result')]
            if not any(
                item.get('id') in ids and item.get('warm_start') in step3_ids
                and self._matches_authoritative_step4(item, research)
                for item in successful
            ):
                raise ValueError('Step4 没有可结束且参数匹配的 MATLAB 真实成功结果')
            self.store.append_event(research_id, EventKind.HUMAN.value, 'FIDELITY_STAGE_DECISION', '用户批准最终阶段结果', payload={'gate_event_id': str(gate.get('id')), 'stage_code': stage_code, 'decision': action}, source='USER')
            self.store.update_research(research_id, status='STOPPED', termination_reason='FINAL_RESULT_APPROVED')
            return self.get_research(research_id)
        if action == 'REPEAT_STAGE': target_stage = stage_code
        else:
            if is_final: raise ValueError('最终阶段必须使用 APPROVE_FINAL')
            gate_ids = set(payload.get('experiment_ids') or [])
            stage_result = any(
                item.get('id') in gate_ids
                and normalize_stage(item.get('fidelity')) == stage_code
                and self._has_usable_stage_result(item)
                for item in self.store.list_experiments(research_id)
            )
            if not stage_result:
                raise ValueError('当前阶段没有有效真实结果，暂不能推进；请重复本阶段或检查求解环境')
            target_stage = f'STEP{rank[stage_code] + 2}'
        self.store.append_event(research_id, EventKind.HUMAN.value, 'FIDELITY_STAGE_DECISION', f'{action}: {stage_code} -> {target_stage}', payload={'gate_event_id': str(gate.get('id')), 'stage_code': stage_code, 'decision': action}, source='USER')
        defaults = dict(research.get('defaults') or {})
        workflow = dict(defaults.get('autonomous_workflow') or {})
        workflow['active_fidelity'] = target_stage
        baseline_id = str(payload.get('best_experiment_id') or '') if action == 'ADVANCE_STAGE' else ''
        workflow['step_authorization'] = {
            'stage': target_stage, 'gate_event_id': str(gate.get('id')),
            'consumed': False, 'authorized_by': action,
            'candidates_limit': 1 if target_stage == 'STEP4' else 3,
            'experiment_ids': [],
            'baseline_experiment_id': baseline_id or None,
        }
        defaults['autonomous_workflow'] = workflow
        self.store.update_research_json(research_id, defaults=defaults)
        self.store.update_research(research_id, status='RUNNING')
        if target_stage == 'STEP4':
            plan_instruction = ('Run exactly one verification experiment at STEP4: inherit the '
                f'approved baseline scheme {baseline_id or "最优方案"} parameters unchanged '
                '(volfrac, beta, beta_max, projection, controller, move) and re-solve on the '
                'MATLAB fine grid with the authoritative configuration.')
        elif action == 'ADVANCE_STAGE':
            plan_instruction = (f'The user approved the round-best scheme {baseline_id or ""} as the '
                f'baseline. Run one comparison round at {target_stage}: derive exactly three '
                'different-direction candidate plans from that baseline; each candidate may vary only '
                'volfrac or one hidden whitelist factor (beta, beta_max, projection, controller, move), '
                'and the three candidates must not repeat the same controlled factor or intent. Compile '
                f'every candidate through policy_compile_intent at {target_stage} with source_experiment '
                f'{baseline_id or ""}, preview and submit all three.')
        else:
            plan_instruction = (f'The user rejected the round-best scheme as a baseline. Regenerate one '
                f'fresh comparison round at {target_stage}: exactly three different-direction candidate '
                'plans rebuilt from the authoritative configuration (not derived from the rejected '
                'scheme); each candidate may vary only volfrac or one hidden whitelist factor (beta, '
                'beta_max, projection, controller, move), and the three candidates must not repeat the '
                'same controlled factor or intent. Compile every candidate through '
                f'policy_compile_intent at {target_stage}, preview and submit all three.')
        prompt = (f'The user selected {action} after {stage_code}. {plan_instruction} '
                  'After all real results of this round are in, compare their grayness and compliance, '
                  'select the round-best scheme, and stop and wait for the next explicit human decision.')
        threading.Thread(target=self._send_pi_or_fallback, args=(research_id, prompt, 'experiment-planning'), daemon=True).start()
        return self.get_research(research_id)

    @staticmethod
    def _matches_authoritative_step4(experiment: dict[str, Any],
                                     research: dict[str, Any]) -> bool:
        if (normalize_stage(experiment.get("fidelity")) != "STEP4"
                or experiment.get("backend") != "matlab"
                or experiment.get("status") != "SUCCESS"):
            return False
        config = ((research.get("defaults") or {}).get("optimization_config") or {})
        if not config:
            return False
        task = build_solver_task(experiment, research)
        params = task["params"]
        expected = {
            "grid3d": [int(config["nelx"]), int(config["nely"]), int(config["nelz"])],
            "penal": float(config["penal"]),
            "rmin": float(config["rmin"]),
            "min_iter": int(config["minIterations"]),
            "max_iter": int(config["maxIterations"]),
            "accuracy": str(config["accuracy"]),
            "filter_strategy": str(config["filterStrategy"]),
        }
        if any(params.get(key) != value for key, value in expected.items()):
            return False
        solver = ((experiment.get("result") or {}).get("solver") or {})
        solver_backend = str(solver.get("backend") or "")
        executed = solver.get("executed_config")
        if not solver_backend.startswith("matlab_mcp_") or not isinstance(executed, dict):
            return False
        material = config.get("material") or {}
        executed_expected = {
            "bc_type": str(config["bcType"]),
            "nelx": int(config["nelx"]),
            "nely": int(config["nely"]),
            "nelz": int(config["nelz"]),
            "accuracy": str(config["accuracy"]),
            "penal": float(config["penal"]),
            "rmin": float(config["rmin"]),
            "min_iterations": int(config["minIterations"]),
            "max_iterations": int(config["maxIterations"]),
            "filter_strategy": str(config["filterStrategy"]),
            "E": float(material["youngsModulusGPa"]),
            "nu": float(material["poissonRatio"]),
            "density_kg_m3": float(material["densityKgM3"]),
            "yield_strength_MPa": float(material["yieldStrengthMPa"]),
            "beta": float(params.get("beta", 1.0)),
            "beta_max": float(params.get("beta_max", params.get("beta", 1.0))),
            "projection": str(task.get("projection", "none")),
            "controller": str(task.get("controller", "fixed_controller")),
            "move_start": float(params.get("move_start", params.get("move", 0.2))),
            "move_end": float(params.get("move_end", params.get("move", 0.2))),
        }
        if not all(executed.get(key) == value for key, value in executed_expected.items()):
            return False
        executed_geometry = executed.get("geometry") or {}
        return (
            list(executed_geometry.get("dimensions") or []) == list(config["dimensions"])
            and executed_geometry.get("unit") == config["unit"]
            and executed_geometry.get("cell_size_m") == config["cellSizeMeters"]
        )

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
        if research["status"] in {"STOPPING", "STOPPED", "STOP_FAILED"} or research.get("termination_reason"):
            return
        if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION":
            workflow = dict(((research.get("defaults") or {}).get("autonomous_workflow") or {}))
            active_stage = str(workflow.get("active_fidelity") or "")
            authorization = dict(workflow.get("step_authorization") or {})
            if not authorization and normalize_stage(active_stage) == "STEP4":
                authorization = dict(workflow.get("step4_authorization") or {})
                if authorization:
                    authorization.setdefault("stage", "STEP4")
            authorized = bool(
                active_stage and authorization and not authorization.get("consumed")
                and normalize_stage(authorization.get("stage")) == normalize_stage(active_stage)
            )
            if not authorized:
                self.store.update_research(research_id, status="READY", termination_reason=None)
                self.store.append_event(
                    research_id, EventKind.HUMAN.value,
                    "DEEP_OPTIMIZATION_PLAN_AWAITING_ACTION",
                    "当前没有未消费的人工 Step 授权；安全模式不会自行执行实验。",
                )
                return
        self._safe_mode_plan_round(research)

    def _safe_mode_plan_round(self, research: dict[str, Any]) -> None:
        """Deterministic fallback for one authorized round.

        A round with an approved baseline derives its candidates from that
        scheme; a round without one (first round, or the user rejected the
        previous best) regenerates fresh comparison candidates. Step1-Step3
        rounds compile three different-direction candidates; Step4 rounds stay
        at one verification candidate that inherits the baseline parameters
        unchanged and re-solves on the MATLAB fine grid.
        """
        research_id = research["id"]
        workflow = dict(((research.get("defaults") or {}).get("autonomous_workflow") or {}))
        active_stage = normalize_stage(workflow.get("active_fidelity") or "STEP1")
        authorization = dict(workflow.get("step_authorization") or {})
        limit = 1 if active_stage == "STEP4" else 3
        experiments = self.store.list_experiments(research_id)
        baseline_id = str(authorization.get("baseline_experiment_id") or "")
        baseline = next((item for item in experiments
                         if item["id"] == baseline_id and item.get("result")), None)
        completed = [item for item in experiments if item.get("result")
                     and not (item.get("result") or {}).get("partial")]
        if active_stage == "STEP4":
            source = baseline or (completed[-1] if completed else None)
            requests = [{"intent": "UPGRADE_FIDELITY",
                         "source_experiment": source["id"] if source else None}]
            requests = [request for request in requests if request["source_experiment"]] or [
                {"intent": "ESTABLISH_BASELINE"}]
        elif baseline is not None:
            quality = baseline["result"].get("quality", {})
            requests = []
            if quality.get("connected_components", 1) != 1:
                requests.append({"intent": "RESTORE_CONNECTIVITY",
                                 "source_experiment": baseline["id"]})
            if quality.get("gray_ratio", 1.0) > research["constraints"].get("gray_max", 0.05):
                requests.append({"intent": "REDUCE_GRAYNESS", "source_experiment": baseline["id"]})
            if not requests:
                requests.append({"intent": "UPGRADE_FIDELITY",
                                 "source_experiment": baseline["id"]})
            rotation = ("beta", "move", "volfrac")
            offset = int(research.get("current_round") or 0)
            for shift in range(len(rotation)):
                factor = rotation[(offset + shift) % len(rotation)]
                requests.append({"intent": "EXPLORE_PARAMETER", "factor": factor,
                                 "source_experiment": baseline["id"]})
        else:
            requests = [
                {"intent": "ESTABLISH_BASELINE"},
                {"intent": "EXPLORE_PARAMETER", "factor": "beta"},
                {"intent": "EXPLORE_PARAMETER", "factor": "move"},
            ]

        def parameter_key(parameters: dict[str, Any]) -> tuple:
            return self.tools.compiler.canonical_parameter_key(parameters)

        def proposal_factors(proposal: dict[str, Any]) -> set[str]:
            return {str(item) for item in (proposal.get("controlled_factors") or [])
                    if item not in {"baseline", "fidelity"}}

        selected: list[dict[str, Any]] = []
        seen: set[tuple] = set()

        def accept(proposals: list[dict[str, Any]],
                   locked_factors: set[str]) -> dict[str, Any] | None:
            for proposal in proposals:
                stage_key = (normalize_stage(proposal.get("fidelity")),
                             parameter_key(proposal.get("parameters")))
                if stage_key in seen:
                    continue
                if proposal_factors(proposal) & locked_factors:
                    continue
                return proposal
            return None

        def remember(proposal: dict[str, Any]) -> None:
            seen.add((normalize_stage(proposal.get("fidelity")),
                      parameter_key(proposal.get("parameters"))))

        errors: list[str] = []

        def compile_request(request: dict[str, Any]) -> list[dict[str, Any]]:
            try:
                return self.tools.policy_compile_intent(
                    research_id, _decision_source="RULE_FALLBACK", **request)
            except Exception as exc:
                # 编译失败必须留痕：静默吞掉会让回退线程无声死亡、流程卡死。
                message = f"编译意图 {request.get('intent')} 失败：{exc}"
                errors.append(message)
                self.store.append_event(research_id, EventKind.SYSTEM.value,
                                        "FALLBACK PLAN COMPILE FAILED", message[:400])
                return []

        # First pass keeps every accepted candidate on a distinct direction.
        locked: set[str] = set()
        for request in requests:
            if len(selected) >= limit:
                break
            proposal = accept(compile_request(request), locked)
            if proposal:
                selected.append(proposal)
                locked |= proposal_factors(proposal)
                remember(proposal)
        # Second pass fills the remaining quota if distinct directions ran out.
        for request in requests:
            if len(selected) >= limit:
                break
            proposal = accept(compile_request(request), set())
            if proposal:
                selected.append(proposal)
                remember(proposal)
        if not selected:
            self.store.update_research(research_id, status="READY", termination_reason=None)
            detail = "；".join(errors[-2:]) if errors else "没有未运行过的新受控配置"
            self.store.append_event(research_id, EventKind.HUMAN.value,
                                    "DEEP_OPTIMIZATION_PLAN_AWAITING_ACTION",
                                    f"当前阶段没有可提交的新受控方案（{detail}）；研究保持未结束状态，等待用户调整或重试。")
            return
        submitted = 0
        for proposal in selected:
            try:
                self.submit_proposal(research_id, proposal["id"])
                submitted += 1
            except ValueError as exc:
                self.store.append_event(research_id, EventKind.SAFETY.value,
                                        "SAFE MODE PLAN REJECTED", str(exc))
            except Exception as exc:
                # 提交阶段的任何异常都必须可见并可恢复，不能让回退线程无声死亡。
                message = f"提案 {proposal['id']} 提交失败：{exc}"
                errors.append(message)
                self.store.append_event(research_id, EventKind.SYSTEM.value,
                                        "SAFE MODE PLAN FAILED", message[:400])
        if submitted:
            self.store.append_event(
                research_id, EventKind.SYSTEM.value, "ROUND_STARTED",
                f"Autonomous round {int(research.get('current_round') or 0) + 1} started at {active_stage}.",
                payload={"stage": active_stage, "required_plans": submitted},
                source="RESEARCH_ORCHESTRATOR")
            self.store.append_event(research_id, EventKind.SYSTEM.value,
                                    "ONE_STEP_PLAN_SUBMITTED",
                                    f"Safe Mode 已提交本轮 {submitted} 个不同方向的受控候选。")
        else:
            self.store.update_research(research_id, status="READY", termination_reason=None)
            detail = "；".join(errors[-2:]) if errors else "候选提交失败"
            self.store.append_event(research_id, EventKind.HUMAN.value,
                                    "DEEP_OPTIMIZATION_PLAN_AWAITING_ACTION",
                                    f"当前阶段候选提交失败（{detail}）；研究保持未结束状态，等待用户调整或重试。")

    def _termination_reason(self, research_id: str) -> str | None:
        research = self._require_research(research_id)
        if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION":
            # Step1-Step4 terminates only through explicit post-run approval.
            return None
        experiments = self.store.list_experiments(research_id)
        successful = [item for item in experiments if item.get("result") and item["status"] == "SUCCESS"]
        if successful:
            required = normalize_stage(research["constraints"].get("required_fidelity", "STEP3"))
            rank = {"STEP1": 0, "STEP2": 1, "STEP3": 2, "STEP4": 3}
            eligible = [item for item in successful
                        if rank.get(normalize_stage(item["fidelity"]), 0) >= rank.get(required, 2)]
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
        used = {item["id"] for item in [*self.store.list_research(), *self.store.list_research(archived=True)]}
        number = 1
        while f"R-{number:03d}" in used:
            number += 1
        return f"R-{number:03d}"

    def list_research(self, archived: bool = False) -> list[dict[str, Any]]:
        return self.store.list_research(archived=archived)

    def archive_research(self, research_id: str) -> dict[str, Any]:
        research = self._require_research(research_id)
        if research.get("archived_at"):
            return research
        # Persist the reversible deletion first. Process termination can take
        # several seconds on Windows and must not block the UI request.
        run_ids: list[tuple[str, str]] = []
        for experiment in self.store.list_experiments(research_id):
            status = str(experiment.get("status", "")).upper()
            run_id = experiment.get("run_id")
            if status in {"WAITING", "QUEUED", "RUNNING", "PENDING"}:
                if run_id:
                    run_ids.append((str(run_id), str(experiment.get("backend") or "")))
                self.store.update_experiment(
                    experiment["id"], status="CANCELLED",
                    error=experiment.get("error") or "Research 已删除，运行已取消",
                )
        for task in self.store.list_subagent_tasks(research_id):
            if str(task.get("status", "")).upper() in {"WAITING", "QUEUED", "RUNNING", "PENDING"}:
                self.store.update_subagent_task(
                    task["id"], status="CANCELLED",
                    error=task.get("error") or "Research 已删除，任务已取消",
                )
        for decision in self.store.list_decisions(research_id):
            if str(decision.get("status", "")).upper() == "PENDING":
                self.store.resolve_decision_if_pending(decision["id"], "REJECTED")
        self.store.update_research(
            research_id, status="STOPPED", termination_reason="DELETED_BY_USER",
        )
        self.store.append_event(
            research_id, EventKind.SYSTEM.value, "RESEARCH_DELETED",
            "研究已终止并移入回收站；已写入的实验证据和制品保留。",
            payload={"reason": "DELETED_BY_USER", "inflight_cancelled": True},
            source="USER",
        )
        archived = self.store.update_research(research_id, archived_at=utc_now())

        def release_inflight() -> None:
            if self.pi_runtime is not None:
                try:
                    self.pi_runtime.cancel(research_id)
                except Exception:
                    pass
            for run_id, backend in run_ids:
                try:
                    if backend == "matlab":
                        self.matlab_worker.cancel(run_id)
                        cancel_event = self._matlab_eng_cancels.get(run_id)
                        if cancel_event is not None:
                            cancel_event.set()
                    else:
                        self.queue.cancel(run_id)
                except Exception:
                    pass
            if self.pi_runtime is not None:
                try:
                    self.pi_runtime.release(research_id)
                except Exception:
                    pass

        threading.Thread(target=release_inflight, daemon=True,
                         name=f"archive-{research_id}").start()
        return archived

    def restore_research(self, research_id: str) -> dict[str, Any]:
        self._require_research(research_id)
        return self.store.update_research(research_id, archived_at=None)

    @staticmethod
    def _workflow_progress(research: dict[str, Any]) -> dict[str, Any]:
        labels = [
            ("context", "读取目标、假设、参数配置与真实基线"),
            ("planning", "生成当前 Step 的受控候选方案组"),
            ("approval", "Policy 与安全校验"),
            ("experiments", "执行当前 Step 的一轮候选实验"),
            ("comparison", "整理当前真实结果"),
            ("selection", "记录当前 Step 最佳有效结果"),
            ("diagnosis", "问题诊断与阶段反思"),
            ("next_round", "形成下一轮建议或终止结论"),
        ]
        events = list(research.get("events") or [])
        start_index = max(
            (index for index, event in enumerate(events)
             if str(event.get("title") or "") == "ROUND_STARTED"),
            default=0,
        )
        round_events = events[start_index:]
        titles = [str(event.get("title") or "") for event in round_events]
        experiments = list(research.get("experiments") or [])
        round_number = max(
            [int(item.get("round_number") or 0) for item in experiments]
            + [int(research.get("current_round") or 0), 1]
        )
        current_experiments = [
            item for item in experiments
            if int(item.get("round_number") or 0) == round_number
        ]
        current_ids = [str(item["id"]) for item in current_experiments]
        terminal = [item for item in current_experiments
                    if str(item.get("status") or "").upper() in {"SUCCESS", "FAILED", "CANCELLED"}]
        pending = [
            item for item in research.get("decisions") or []
            if item.get("status") == "PENDING"
            and (not item.get("experiment_id") or item.get("experiment_id") in current_ids)
        ]
        batch_complete = "EXPERIMENT_BATCH_COMPLETED" in titles or "WORKFLOW_ROUND_COMPLETED" in titles
        stopped = str(research.get("status") or "").upper() in {"STOPPED", "COMPLETED", "FAILED"}
        baseline = (research.get("defaults") or {}).get("engineering_scheme_baseline") or {}
        baseline_ids = [str(value) for value in (baseline.get("schemeId"), baseline.get("runId")) if value]
        reflection_events = [
            event for event in round_events
            if (event.get("payload") or {}).get("workflow_step")
            and (event.get("payload") or {}).get("reflection")
        ]
        reflections_by_step: dict[str, list[dict[str, Any]]] = {}
        for event in reflection_events:
            step_key = str((event.get("payload") or {}).get("workflow_step") or "")
            if step_key:
                reflections_by_step.setdefault(step_key, []).append(event)
        best = research.get("best_experiment") or {}

        statuses: dict[str, str] = {key: "pending" for key, _ in labels}
        if "ROUND_STARTED" in titles or "WORKFLOW_CONTEXT_COMPLETED" in titles:
            statuses["context"] = "completed"
            statuses["planning"] = "active"
        if current_experiments or any(title == "THREE_PLAN_SUBMITTED" for title in titles):
            statuses["planning"] = "completed"
            statuses["approval"] = "active" if pending else "completed"
        if current_experiments and not pending:
            statuses["experiments"] = "active"
        if batch_complete or (current_experiments and len(terminal) == len(current_experiments)):
            statuses["experiments"] = "completed"
        if batch_complete:
            statuses.update(comparison="completed", selection="completed", diagnosis="completed")
            statuses["next_round"] = "completed" if "WORKFLOW_ROUND_COMPLETED" in titles or stopped else "active"
        if stopped and terminal:
            statuses["next_round"] = "completed"

        completed_units = sum(1.0 for key, _ in labels if statuses[key] == "completed")
        if statuses["experiments"] == "active" and current_experiments:
            completed_units += min(1.0, len(terminal) / max(1, len(current_experiments)))
        percent = int(round(100 * completed_units / len(labels)))
        active_key = next((key for key, _ in labels if statuses[key] == "active"), None)
        stage = active_key or ("completed" if percent == 100 else "idle")
        experiment_result = f"已完成 {len(terminal)} / {max(1, len(current_experiments))} 次当前 Step 实验"
        experiment_reflection = "；".join(
            str((event.get("payload") or {}).get("reflection") or event.get("body") or "")
            for event in reflections_by_step.get("experiments", [])[-3:]
        )
        steps = []
        for key, label in labels:
            evidence_ids = baseline_ids if key == "context" else current_ids
            result = None
            reflection = None
            next_action = None
            if key == "context":
                result = "已导入工程基线" if baseline_ids else "使用当前 Research 已完成实验或历史最优结果"
                reflection = "证据优先级：工程基线 → 当前真实实验 → 历史最优。"
                next_action = "生成本轮受控候选方案组"
            elif key == "planning":
                result = f"已形成 {len(current_experiments)} 个受控候选方案"
                if reflections_by_step.get(key):
                    reflection = str((reflections_by_step[key][-1].get("payload") or {}).get("reflection") or "") or None
                next_action = "进入 Policy 编译与审批"
            elif key == "approval":
                result = f"待审批 {len(pending)} 项" if pending else ("审批边界已满足" if current_experiments else None)
                if reflections_by_step.get(key):
                    reflection = str((reflections_by_step[key][-1].get("payload") or {}).get("reflection") or "") or None
                next_action = "批准后执行真实实验" if pending else "执行候选实验"
            elif key == "experiments":
                result = experiment_result
                reflection = experiment_reflection or None
                next_action = "等待真实终态" if statuses[key] == "active" else "比较真实结果"
            elif key == "comparison" and batch_complete:
                result = f"比较 {len(terminal)} 个真实终态方案"
                event = reflections_by_step.get(key, [])[-1] if reflections_by_step.get(key) else None
                reflection = str(((event or {}).get("payload") or {}).get("reflection") or "失败方案只保留失败原因，不补造指标。")
            elif key == "selection" and batch_complete:
                result = f"当前最优：{best.get('id')}" if best else "本轮没有真实成功方案"
                evidence_ids = [str(best.get("id"))] if best else current_ids
                event = reflections_by_step.get(key, [])[-1] if reflections_by_step.get(key) else None
                reflection = str(((event or {}).get("payload") or {}).get("reflection") or "") or None
            elif key == "diagnosis" and batch_complete:
                result = "已完成最优方案弱点诊断与逐方案反思"
                event = reflections_by_step.get(key, [])[-1] if reflections_by_step.get(key) else None
                reflection = str(((event or {}).get("payload") or {}).get("reflection") or experiment_reflection or "诊断仅引用真实实验与工程基线。")
            elif key == "next_round" and statuses[key] == "completed":
                result = research.get("termination_reason") or "已形成下一轮受控建议"
                event = reflections_by_step.get(key, [])[-1] if reflections_by_step.get(key) else None
                reflection = str(((event or {}).get("payload") or {}).get("reflection") or "") or None
                next_action = "等待实验者选择继续当前 Step 或进入下一 Step"
            steps.append({
                "id": key, "label": label, "status": statuses[key],
                "summary": label, "result": result, "reflection": reflection,
                "evidenceIds": evidence_ids, "experimentIds": current_ids,
                "nextAction": next_action,
            })
        return {
            "round": round_number, "stage": stage, "percent": percent, "steps": steps,
            "budgetUsed": 0,
            "budgetTotal": 0,
        }

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
        research["subagent_tasks"] = self.store.list_subagent_tasks(research_id)
        research["hypotheses"] = self.store.list_hypotheses(research_id)
        research["artifact_lineage"] = self.store.list_artifacts(research_id)
        successful = [e for e in research["experiments"] if e["status"] == "SUCCESS" and e["result"]]
        rank = {"STEP1": 0, "STEP2": 1, "STEP3": 2, "STEP4": 3}
        highest = max((rank.get(normalize_stage(item["fidelity"]), 0) for item in successful), default=0)
        comparable = [item for item in successful
                      if rank.get(normalize_stage(item["fidelity"]), 0) == highest]
        research["best_experiment"] = min(
            comparable, key=lambda e: e["result"].get("objective", {}).get("compliance", float("inf")),
            default=None,
        )
        research["workflow"] = self._workflow_progress(research)
        return research

    def create_experiment(self, research_id: str,
                          request: ExperimentCreate | dict[str, Any]) -> dict[str, Any]:
        # Serialize creation so one human decision cannot accidentally enqueue
        # multiple experiments for the same Step.
        with self._experiment_creation_lock:
            return self._create_experiment_for_authorized_step(research_id, request)

    def _create_experiment_for_authorized_step(
        self, research_id: str, request: ExperimentCreate | dict[str, Any]
    ) -> dict[str, Any]:
        research = self._require_research(research_id)
        if isinstance(request, ExperimentCreate):
            model = request
        else:
            defaults = (research.get("defaults") or {}).get("experiment", {})
            seed = {"mesh_level": defaults.get("mesh_level", "coarse"),
                    "parameters": defaults.get("parameters", {})}
            model = ExperimentCreate.model_validate(_deep_merge(seed, request))
        code = _validate_fidelity_backend(model.fidelity, model.backend)
        defaults_state = dict(research.get("defaults") or {})
        workflow_state = dict(defaults_state.get("autonomous_workflow") or {})
        deep_active = (
            normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION"
            and bool(workflow_state.get("active_fidelity"))
        )
        authorization = dict(workflow_state.get("step_authorization") or {})
        # Accept the short-lived 2.1.0 development key as compatibility input,
        # but persist only the generalized all-Step authorization contract.
        if not authorization and code == "STEP4":
            authorization = dict(workflow_state.get("step4_authorization") or {})
            if authorization:
                authorization.setdefault("stage", "STEP4")
        # One human authorization covers one comparison round: three
        # different-direction candidates at Step1-Step3, one verification run
        # at Step4. Older persisted authorizations default to the same quota.
        limit = int(authorization.get("candidates_limit") or (1 if code == "STEP4" else 3))
        issued = [str(item) for item in (authorization.get("experiment_ids") or [])]
        if not issued and authorization.get("experiment_id"):
            issued = [str(authorization["experiment_id"])]
        if deep_active and (
            not authorization
            or authorization.get("consumed")
            or len(issued) >= limit
            or normalize_stage(authorization.get("stage")) != code
            or normalize_stage(workflow_state.get("active_fidelity")) != code
        ):
            if (limit > 1 and authorization
                    and normalize_stage(authorization.get("stage")) == code
                    and normalize_stage(workflow_state.get("active_fidelity")) == code
                    and len(issued) >= limit):
                raise ValueError(
                    f"{stage_label(code)} 本轮 {limit} 个候选名额已用完；"
                    "请等待本轮实验完成并作出阶段决策"
                )
            raise ValueError(
                f"{stage_label(code)} requires one unconsumed human authorization for the active Step"
            )
        parameters = {**model.parameters, **research["locks"]}
        experiment_id = self._next_experiment_id(research_id)
        draft = {"id": experiment_id, "research_id": research_id, **model.model_dump(),
                 "parameters": parameters,
                 "round_number": int(research.get("current_round", 0)) + 1}
        if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION" and (
            (research.get("defaults") or {}).get("optimization_config")
        ):
            parameters = build_solver_task(draft, research)["params"]
            draft["parameters"] = parameters
        safety = self.orchestrator.inspect_proposal(draft)
        if not safety["safe"]:
            self.store.append_event(research_id, EventKind.SAFETY.value, "PROPOSAL REJECTED",
                                    str(safety["reason"]), payload=safety)
            raise ValueError(f"Safety Policy rejected proposal: {safety['reason']}")
        requires_approval = model.requires_approval or bool(safety["requires_approval"]) or \
            requires_human_approval(research["mode"], str(safety["risk"]), model.fidelity)
        experiment = self.store.create_experiment({
            **draft, "status": ExperimentStatus.WAITING.value, "safety": safety["risk"],
            "requires_approval": bool(requires_approval),
        })
        if deep_active:
            issued.append(experiment_id)
            workflow_state["step_authorization"] = {
                **authorization, "stage": code, "candidates_limit": limit,
                "experiment_ids": issued,
                "consumed": len(issued) >= limit,
                "experiment_id": experiment_id,
            }
            workflow_state.pop("step4_authorization", None)
            defaults_state["autonomous_workflow"] = workflow_state
            self.store.update_research_json(research_id, defaults=defaults_state)
        body = (f"Purpose: {model.purpose}\n\nFidelity: {model.fidelity}\n\n"
                f"Parameters: {json.dumps(parameters, ensure_ascii=False)}")
        self.store.append_event(research_id, EventKind.SAFETY.value, f"PROPOSAL {experiment_id}",
                                f"Risk: {safety['risk']}\n\n{safety['reason']}", experiment_id, safety)
        self.store.append_event(research_id, EventKind.EXPERIMENT.value,
                                f"PROPOSED EXPERIMENT {experiment_id}", body, experiment_id)
        if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION":
            parameter_digest = hashlib.sha256(
                json.dumps(parameters, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
            ).hexdigest()
            self.store.append_event(
                research_id, EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                f"{experiment_id} 已作为受控候选方案进入科研流程。", experiment_id,
                {
                    "workflow_step": "planning", "status": "completed",
                    "experiment_ids": [experiment_id],
                    "evidence_ids": list(model.evidence_ids or []),
                    "result": {"fidelity": model.fidelity, "parameter_digest": parameter_digest},
                    "reflection": "该候选只表达经 Policy 与 Safety 校验的实验意图；尚无求解结果，不把计划当作证据。",
                    "next_action": "等待审批或进入真实实验",
                },
                source="RESEARCH_ORCHESTRATOR",
            )
        if requires_approval:
            decision_id = f"D-{uuid.uuid4().hex[:8].upper()}"
            self.store.create_decision({
                "id": decision_id, "research_id": research_id, "experiment_id": experiment_id,
                "intent": "RUN_EXPERIMENT", "reason": model.purpose,
                "proposal": {"parameters": parameters, "fidelity": model.fidelity},
                "risk": safety["risk"], "status": DecisionStatus.PENDING.value,
                "source": model.decision_source, "evidence_ids": model.evidence_ids,
            })
            experiment["decision_id"] = decision_id
        else:
            if normalize_mode(research.get("mode")) == "DEEP_OPTIMIZATION":
                self.store.append_event(
                    research_id, EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                    f"{experiment_id} 已通过自动 Policy 与 Safety 边界。", experiment_id,
                    {
                        "workflow_step": "approval", "status": "completed",
                        "experiment_ids": [experiment_id],
                        "evidence_ids": list(model.evidence_ids or []),
                    "reflection": "该 Step 已通过 Policy 与 Safety 校验；Step4 同时消费上一阶段人工授权。放行不等同于结果成功。",
                        "next_action": "执行真实实验并等待确定性评估",
                    },
                    source="POLICY_ENGINE",
                )
            self.run_experiment(experiment_id)
        return experiment

    def _next_experiment_id(self, research_id: str) -> str:
        # 实验编号按 Research 独立从 E001 开始；存储 ID 带研究前缀以避免
        # 不同研究的运行记录混淆（制品目录同样按研究分文件夹存放）。
        ordinal = len(self.store.list_experiments(research_id)) + 1
        candidate = f"{research_id}-E{ordinal:03d}"
        while self.store.get_experiment(candidate) is not None:
            ordinal += 1
            candidate = f"{research_id}-E{ordinal:03d}"
        return candidate

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment = self.store.get_experiment(experiment_id)
        if not experiment:
            raise KeyError(f"Experiment {experiment_id} does not exist")
        if experiment["run_id"] and experiment["status"] in {"WAITING", "RUNNING"}:
            self._sync_progress(experiment)
            experiment = self.store.get_experiment(experiment_id)
        return experiment

    def _experiment_lock(self, experiment_id: str) -> threading.RLock:
        with self._experiment_locks_guard:
            lock = self._experiment_locks.get(experiment_id)
            if lock is None:
                lock = self._experiment_locks[experiment_id] = threading.RLock()
            return lock

    def _require_approved_run_decision(self, experiment: dict[str, Any],
                                       research: dict[str, Any]) -> None:
        decisions = [
            item for item in self.store.list_decisions(research["id"])
            if item.get("experiment_id") == experiment["id"]
            and item.get("intent") == "RUN_EXPERIMENT"
        ]
        requires_approval = requires_human_approval(
            str(research["mode"]),
            str(experiment.get("safety", "LOW")),
            str(experiment["fidelity"]),
        )
        if not bool(experiment.get("requires_approval")) and not requires_approval and not decisions:
            return
        current = decisions[-1] if decisions else None
        status = str(current["status"]) if current else "MISSING"
        if status != DecisionStatus.APPROVED.value:
            raise ValueError(
                f"Experiment {experiment['id']} requires an explicit APPROVED decision "
                f"in Research State (current: {status})"
            )

    def _claim_experiment_for_run(self, experiment_id: str) -> tuple[dict[str, Any], dict[str, Any], bool]:
        with self._experiment_lock(experiment_id):
            experiment = self.get_experiment(experiment_id)
            research = self._require_research(experiment["research_id"])
            _validate_fidelity_backend(experiment["fidelity"], experiment["backend"])
            self._require_approved_run_decision(experiment, research)
            if research["status"] in {"PAUSED", "STOPPED"}:
                raise ValueError(f"Research is {research['status'].lower()}")
            if experiment["status"] not in {"WAITING", "FAILED", "CANCELLED"}:
                return experiment, research, False
            claim_id = f"claim_{uuid.uuid4().hex[:12]}"
            if not self.store.claim_experiment_for_run(experiment_id, claim_id):
                current = self.store.get_experiment(experiment_id)
                if current is None:
                    raise KeyError(f"Experiment {experiment_id} does not exist")
                return current, research, False
            claimed = self.store.get_experiment(experiment_id)
            if claimed is None:
                raise KeyError(f"Experiment {experiment_id} does not exist")
            return claimed, research, True

    def _prepare_claimed_experiment(self, experiment: dict[str, Any],
                                    research: dict[str, Any]) -> tuple[dict, dict, Any]:
        task = build_solver_task(experiment, research)
        if experiment.get("warm_start"):
            source = self.store.get_experiment(experiment["warm_start"])
            source_result = (source or {}).get("result") or {}
            density = (source_result.get("artifacts") or {}).get("density")
            if density is not None:
                fidelity_code = normalize_stage(experiment.get("fidelity"))
                if fidelity_code == "STEP4" and (source or {}).get("backend") == "python3d":
                    import numpy as np
                    array = np.asarray(density, dtype=float)
                    if array.ndim != 3 or not np.isfinite(array).all():
                        raise ValueError("Step3 warm-start density must be a finite 3D array")
                    density = array.transpose(1, 2, 0).tolist()
                task["params"]["initial_density"] = density
        cache_task = {**task, "backend": experiment["backend"]}
        fidelity_code = normalize_stage(experiment.get("fidelity"))
        solver_entry = self.project_root / (
            "求解器模块/TopOpt-3D/TopOpt-3D/topopt3d_main.m"
            if fidelity_code in {"STEP3", "STEP4"} else
            "求解器模块/2D/TopOpt_integrated/TopOpt_integrated/topopt_main.m")
        if solver_entry.is_file():
            cache_task["solver_entry_sha256"] = hashlib.sha256(solver_entry.read_bytes()).hexdigest()
        contract_raw = json.dumps(research.get("contract", {}), sort_keys=True,
                                  ensure_ascii=False, default=str).encode("utf-8")
        cache_task["research_contract_sha256"] = hashlib.sha256(contract_raw).hexdigest()
        cached = self.cache.get(cache_task)
        if experiment["backend"] == "matlab" and cached is not None:
            backend = str((cached.get("solver") or {}).get("backend", ""))
            if not backend.startswith("matlab_mcp_"):
                cached = None
        return task, cache_task, cached

    def _fail_unsubmitted_claim(self, experiment_id: str, exc: Exception) -> None:
        with self._experiment_lock(experiment_id):
            current = self.store.get_experiment(experiment_id)
            if current and current["status"] == "RUNNING" and str(current.get("run_id", "")).startswith("claim_"):
                self.store.update_experiment(
                    experiment_id, status="FAILED", progress=1.0,
                    completed_at=utc_now(), error=str(exc),
                )

    def run_experiment(self, experiment_id: str) -> dict[str, Any]:
        experiment, research, claimed = self._claim_experiment_for_run(experiment_id)
        if not claimed:
            return experiment
        try:
            task, cache_task, cached = self._prepare_claimed_experiment(experiment, research)
        except Exception as exc:
            self._fail_unsubmitted_claim(experiment_id, exc)
            raise
        if cached is not None:
            from concurrent.futures import Future
            future = Future()
            future.set_result(cached)
            try:
                self.store.update_experiment(experiment_id, run_id="cache_hit", progress=1.0, cached=1,
                                             result_source="CACHED_REAL_RESULT")
            except Exception as exc:
                self._fail_unsubmitted_claim(experiment_id, exc)
                raise
            self._complete_experiment(experiment_id, "cache_hit", future, cache_task)
            return self.get_experiment(experiment_id)
        try:
            if experiment["backend"] == "matlab":
                # Step4 复用"基础实现"工程 MATLAB 链路（run_topopt_job.m）：
                # 独立 MATLAB 进程、逐轮快照/状态/PNG 制品、进度回调与取消。
                run_id = self._start_step4_matlab(experiment, research, cache_task)
                self.store.append_event(research["id"], EventKind.EXPERIMENT.value,
                                        "MATLAB ENGINEERING STARTED",
                                        "Step4 验证已按基础实现同款工程链路启动（run_topopt_job + 逐轮快照）。",
                                        experiment_id, {"backend": "matlab_eng"})
            else:
                run_id = self.queue.submit(
                    task, backend=experiment["backend"],
                    done=lambda rid, future: self._complete_experiment(
                        experiment_id, rid, future, cache_task),
                )
        except Exception as exc:
            self._fail_unsubmitted_claim(experiment_id, exc)
            raise
        try:
            persisted = self.store.update_experiment(experiment_id, run_id=run_id,
                                                     result_source="LIVE_REAL_RUN")
            if not persisted or persisted.get("run_id") != run_id:
                raise RuntimeError("run_id update did not persist")
        except Exception as exc:
            claim_id = experiment.get("run_id")
            raise RuntimeError(
                f"Solver was submitted as {run_id}, but run_id persistence failed; "
                f"durable claim remains {claim_id}"
            ) from exc
        self.store.update_research(research["id"], status="RUNNING")
        self.store.append_event(research["id"], EventKind.EXPERIMENT.value,
                                f"EXPERIMENT {experiment_id} STARTED",
                                f"{experiment['fidelity']} is running in the background.", experiment_id)
        return self.get_experiment(experiment_id)

    def _packaged_matlab_root(self) -> Path:
        """Step4 工程链路的 MATLAB 资源根：打包运行时用安装目录 resources，
        开发运行时回退源码树。__file__ 在 onefile 包内指向临时解包目录，
        不能作为 matlab/engineering 与求解器模块的定位依据。"""
        resource_root = os.environ.get("TOPPILOT_RESOURCE_ROOT")
        if resource_root:
            packaged = Path(resource_root)
            if (packaged / "matlab" / "engineering").is_dir():
                return packaged
        return Path(__file__).resolve().parents[2]

    def _engineering_matlab_executable(self) -> Path:
        matlab_root = Path(self.matlab_worker.connector.matlab_root or "")
        executable = matlab_root / "bin" / "matlab.exe" if os.name == "nt" else matlab_root / "bin" / "matlab"
        if not executable.is_file():
            raise RuntimeError(f"未找到 MATLAB 可执行文件：{executable}")
        return executable

    def _read_fortran_frame(self, path: Path, shape: list[int]) -> list:
        import numpy as np
        raw = np.fromfile(path, dtype="<f4")
        dims = [int(dim) for dim in shape]
        if raw.size != int(np.prod(dims)) or not dims:
            raise ValueError(f"快照帧尺寸不匹配：{path.name}")
        return np.reshape(raw, dims, order="F").tolist()

    def _publish_matlab_progress(self, experiment_id: str, research_id: str, iteration: int,
                                 total: int, density_2d: list, density_3d: list,
                                 history: list, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - getattr(self, "_matlab_progress_ts", 0.0) < 1.5:
            return
        self._matlab_progress_ts = now
        try:
            self.store.update_experiment(
                experiment_id,
                current_iteration=int(iteration),
                progress=min(1.0, iteration / max(total, 1)),
                result={"status": "running", "partial": True,
                        "task_id": experiment_id, "experiment_group": experiment_id,
                        "objective": {}, "constraints": {}, "quality": {},
                        "solver": {"backend": "matlab_eng_3d"},
                        "artifacts": {"density": density_2d,
                                      "density_3d_live": density_3d,
                                      "history": history}})
            self.store.append_event(
                research_id, EventKind.EXPERIMENT.value,
                f"MATLAB PROGRESS {experiment_id}",
                f"实时快照：迭代 {iteration}/{total}", experiment_id)
        except Exception:
            pass

    def _start_step4_matlab(self, experiment: dict[str, Any], research: dict[str, Any],
                            cache_task: dict[str, Any] | None) -> str:
        """Step4 复用"基础实现"工程 MATLAB 链路：独立 -batch 进程执行
        run_topopt_job.m（逐轮快照/状态/可视化制品），进度实时回传科研面板。"""
        from concurrent.futures import Future
        experiment_id = experiment["id"]
        run_id = f"run_eng_{experiment_id.lower()}"
        cancel = threading.Event()
        self._matlab_eng_cancels[run_id] = cancel
        future = Future()

        def runner() -> None:
            try:
                result = self._run_step4_matlab_task(experiment, research, cancel)
                future.set_result(result)
            except BaseException as exc:  # noqa: BLE001 - 完整失败原因进入实验记录
                future.set_exception(exc)

        def done_callback(done: Future) -> None:
            self._complete_experiment(experiment_id, run_id, done, cache_task)

        threading.Thread(target=runner, daemon=True,
                         name=f"step4-matlab-{experiment_id}").start()
        future.add_done_callback(done_callback)
        return run_id

    def _run_step4_matlab_task(self, experiment: dict[str, Any], research: dict[str, Any],
                               cancel: threading.Event) -> dict[str, Any]:
        from topoptpilot_desktop.engineering.matlab_runner import run_matlab_batch
        from solver.result_schema import connected_components as density_components
        experiment_id = experiment["id"]
        config = ((research.get("defaults") or {}).get("optimization_config") or {})
        params = experiment.get("parameters") or {}
        material_cfg = config.get("material") or {}
        nelx = int(config.get("nelx") or 48)
        nely = int(config.get("nely") or 16)
        nelz = int(config.get("nelz") or 12)
        # MATLAB 参数信封（与正式链路同一边界）；存量研究中的非法组合
        # （beta > beta_max）在此自动归一，保证演示流程不卡。
        volfrac, penal, rmin = float(params.get("volfrac", .4)), float(params.get("penal", 3.)), float(params.get("rmin", 2.))
        beta = float(params.get("beta", 1.))
        beta_max = max(float(params.get("beta_max", beta) or beta), beta)
        move = float(params.get("move", .2))
        projection = str(params.get("projection") or "none")
        controller = str(params.get("controller") or "fixed_controller")
        if not (.1 <= volfrac <= .7 and .75 <= rmin <= 4 and 1 <= penal <= 5
                and 1 <= beta <= 64 and beta <= beta_max <= 64
                and projection in {"none", "heaviside_projection"}
                and controller in {"fixed_controller", "periodic_controller"}
                and .01 <= move <= .5):
            raise RuntimeError("Task escaped the approved MATLAB parameter envelope")
        packaged_root = self._packaged_matlab_root()
        task = {
            "task_id": experiment_id, "dimension": "3d",
            "load_case": str(config.get("bcType") or "cantilever"),
            "solver_dir": str(packaged_root / "求解器模块" / "TopOpt-3D" / "TopOpt-3D"),
            "geometry": {"nelx": nelx, "nely": nely, "nelz": nelz,
                         "dimensions": [int(v) for v in (config.get("dimensions") or [48, 16, 12])],
                         "unit": str(config.get("unit") or "m"),
                         "cell_size_m": float(config.get("cellSizeMeters") or 1.0)},
            "params": {"volfrac": volfrac, "penal": penal, "rmin": rmin,
                       "max_iter": int(config.get("maxIterations", 80)),
                       "min_iter": int(config.get("minIterations", 10)),
                       "filter_strategy": str(config.get("filterStrategy") or "fixed"),
                       "accuracy": str(config.get("accuracy") or "high"),
                       "beta": beta, "beta_max": beta_max,
                       "projection": projection, "controller": controller, "move": move},
            "material": {
                "preset": str(material_cfg.get("preset") or "structural-steel"),
                "name": str(material_cfg.get("name") or "结构钢"),
                "E": float(material_cfg.get("youngsModulusGPa") or 200.0),
                "E_GPa": float(material_cfg.get("youngsModulusGPa") or 200.0),
                "nu": float(material_cfg.get("poissonRatio") or 0.3),
                "density_kg_m3": float(material_cfg.get("densityKgM3") or 7850.0),
                "yield_strength_MPa": float(material_cfg.get("yieldStrengthMPa") or 250.0),
            },
        }
        output_dir = self.data_dir / research["id"] / "matlab_eng" / experiment_id
        total_iterations = int(config.get("maxIterations", 80))
        history: list[dict[str, Any]] = []
        self._publish_matlab_progress(experiment_id, research["id"], 0, total_iterations,
                                      [], [], [], force=True)

        def cancelled() -> bool:
            return cancel.is_set()

        # 实时进度：独立 watcher 扫描唯一名帧文件（不读覆盖型清单/状态，
        # 从机制上规避 Windows 文件占用冲突）。
        def frame_iteration(path: Path) -> int:
            try:
                return int(path.stem.split("_")[1])
            except (IndexError, ValueError):
                return 0

        def watcher() -> None:
            snapshots_dir = output_dir / "snapshots"
            last_iteration = 0
            last_emit = 0.0
            while not done_flag.wait(0.3):
                try:
                    if not snapshots_dir.is_dir():
                        continue
                    latest = None
                    latest_iteration = 0
                    for frame_path in snapshots_dir.glob("iter_*_density.bin"):
                        iteration = frame_iteration(frame_path)
                        if iteration > latest_iteration:
                            latest_iteration = iteration
                            latest = frame_path
                    if latest is None or latest_iteration <= last_iteration:
                        continue
                    now = time.monotonic()
                    if now - last_emit < 1.2:
                        continue
                    meta_path = snapshots_dir / f"iter_{latest_iteration:04d}_meta.json"
                    compliance = None
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        compliance = meta.get("objective")
                    except Exception:
                        compliance = None
                    density_3d = self._read_fortran_frame(latest, [nely, nelx, nelz])
                    z_mid = len(density_3d[0][0]) // 2 if density_3d and density_3d[0] else 0
                    density_2d = [[row[column][z_mid] for column in range(len(row))]
                                  for row in density_3d]
                    history.append({"iteration": latest_iteration,
                                    "compliance": compliance})
                    self._publish_matlab_progress(experiment_id, research["id"],
                                                  latest_iteration, total_iterations,
                                                  density_2d, density_3d, list(history))
                    last_iteration = latest_iteration
                    last_emit = now
                except Exception:
                    continue

        stop_watching = threading.Event()
        done_flag = stop_watching
        watcher_thread = threading.Thread(target=watcher, daemon=True,
                                          name=f"step4-snapshots-{experiment_id}")
        watcher_thread.start()

        summary = run_matlab_batch(
            self._engineering_matlab_executable(), task, output_dir,
            source_root=packaged_root / "matlab" / "engineering",
            cancel=cancelled, timeout_seconds=7200, progress=None)
        stop_watching.set()
        density_path = output_dir / "snapshots" / "final_density.bin"
        manifest_path = output_dir / "result_manifest.json"
        density_3d: list = []
        shape: list[int] = []
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            shape = [int(dim) for dim in manifest.get("shape") or []]
            density_3d = self._read_fortran_frame(output_dir / manifest.get("density_file", "final_density.bin"), shape)
        except Exception:
            if not density_3d and history:
                density_3d = []
        import numpy as np
        quality: dict[str, Any] = {"gray_ratio": summary.get("gray_ratio")}
        if shape and len(shape) == 3 and density_3d:
            cube = np.asarray(density_3d, dtype=float)
            quality["gray_ratio"] = round(float(density_gray_ratio(cube)), 4)
            quality["connected_components"] = int(density_components(cube))
        objective_history = [
            {"iteration": index + 1, "compliance": float(value)}
            for index, value in enumerate(summary.get("objective_history") or [])
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        return {
            "status": "converged", "task_id": experiment_id,
            "experiment_group": experiment_id,
            "objective": {"compliance": summary.get("objective")},
            "constraints": {"volume_fraction": summary.get("volume_fraction")},
            "quality": quality,
            "solver": {"backend": "matlab_eng_3d", "iterations": int(summary.get("iterations") or 0),
                       "solver_entry": summary.get("solver_entry"),
                       "executed_config": task["params"]},
            "artifacts": {"density": density_3d,
                          "history": objective_history},
        }

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
            if (experiment["status"] == "CANCELLED"
                    or research["status"] in {"STOPPING", "STOPPED", "STOP_FAILED"}
                    or research.get("active_run_id") != experiment.get("research_run_id")):
                self.store.update_experiment(experiment_id, status="CANCELLED", completed_at=utc_now())
                self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                        f"EXPERIMENT {experiment_id} CANCELLED",
                                        "The completed worker output was discarded after /stop.", experiment_id,
                                        research_run_id=experiment.get("research_run_id"))
                return
            try:
                result = future.result()
                analysis = self.orchestrator.analyze(research, result, experiment)
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
                    solver_variant=result.get("solver", {}).get("solver_variant", "reference_cpu"),
                    acceleration_mode=result.get("solver", {}).get("acceleration_mode", "cpu"),
                    solver_sha256=result.get("solver", {}).get("solver_entry_sha256"),
                    task_hash=result.get("solver", {}).get("task_sha256"),
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
                self.store.append_event(
                    research["id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                    f"{experiment_id} 已依据真实求解结果完成阶段反思。",
                    experiment_id,
                    {
                        "workflow_step": "experiments", "status": status.lower(),
                        "experiment_ids": [experiment_id],
                        "evidence_ids": list(experiment.get("evidence_ids") or []) + [experiment_id],
                        "result": {
                            "compliance": result.get("objective", {}).get("compliance"),
                            "volume_fraction": result.get("constraints", {}).get("volume_fraction"),
                            "gray_ratio": result.get("quality", {}).get("gray_ratio"),
                            "connected_components": result.get("quality", {}).get("connected_components"),
                            "maximum_von_mises": result.get("quality", {}).get("maximum_von_mises"),
                            "stress_unit": result.get("quality", {}).get("stress_unit"),
                            "stress_unit_trusted": result.get("quality", {}).get("stress_unit_trusted"),
                        },
                        "reflection": self._chinese_reflection(status, analysis["evaluation"]),
                        "next_action": analysis["feedback"],
                    },
                    source="DETERMINISTIC_EVALUATOR",
                )
            except Exception as exc:
                failure_type = ("MATLAB_INFRASTRUCTURE" if isinstance(exc, MatlabMcpError)
                                or experiment["backend"] == "matlab" else "INFRASTRUCTURE")
                failure_result = {
                    "status": "failed", "objective": {}, "constraints": {}, "quality": {},
                    "solver": {"backend": experiment["backend"], "iterations": 0,
                               "failure_type": failure_type},
                    "evaluation": {"success": False, "failure_type": failure_type,
                                   "reason": str(exc)},
                    "artifacts": {},
                }
                self.store.update_experiment(experiment_id, status="FAILED", progress=1.0,
                                             result=failure_result, completed_at=utc_now(), error=str(exc))
                self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                        f"EXPERIMENT {experiment_id} FAILED", str(exc), experiment_id,
                                        {"failure_type": failure_type,
                                         "matlab_health": (self.matlab_worker.health()
                                                           if experiment["backend"] == "matlab" else None),
                                         "failed_at": utc_now()})
                self.store.append_event(
                    research["id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                    f"{experiment_id} 失败，已保留真实失败原因并纳入方案比较。",
                    experiment_id,
                    {
                        "workflow_step": "experiments", "status": "failed",
                        "experiment_ids": [experiment_id], "evidence_ids": [experiment_id],
                        "result": {"failure_type": failure_type, "reason": str(exc)},
                        "reflection": "该方案没有产生可用于结论的真实指标，不以模拟值补齐。",
                        "next_action": "比较其余真实方案并诊断失败原因",
                    },
                    source="DETERMINISTIC_EVALUATOR",
                )
            running = [e for e in self.store.list_experiments(research["id"])
                       if e["status"] in {"WAITING", "RUNNING"}]
            round_ready = not running
            current = None
            if round_ready:
                current = self._require_research(research["id"])
                if normalize_mode(current.get("mode")) == "DEEP_OPTIMIZATION":
                    # 缓存命中的候选会在创建循环内同步完成；只有当本轮授权的
                    # 全部候选都到达终态时才允许收轮，避免提前弹窗、重复弹窗
                    # 与轮次跳号。
                    authorization = dict(((current.get("defaults") or {}).get(
                        "autonomous_workflow") or {}).get("step_authorization") or {})
                    authorized_ids = [str(item) for item in
                                      (authorization.get("experiment_ids") or [])]
                    if authorized_ids:
                        statuses = {item["id"]: item["status"]
                                    for item in self.store.list_experiments(research["id"])}
                        round_ready = all(
                            statuses.get(item) in {"SUCCESS", "FAILED", "CANCELLED"}
                            for item in authorized_ids)
                if round_ready and self._pending_fidelity_stage_gate(research["id"]) is not None:
                    round_ready = False
            if round_ready and current is not None:
                next_round = int(current.get("current_round", 0)) + 1
                self.store.update_research(research["id"],
                                           current_round=next_round)
                try:
                    round_paths = self.generate_round_report(research["id"], next_round)
                    self.store.append_event(
                        research["id"], EventKind.SYSTEM.value, "ROUND REPORT READY",
                        round_paths["markdown"], payload=round_paths,
                        source="REPORT_WRITER", event_type="REPORT_READY")
                except Exception as report_error:
                    self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                            "ROUND REPORT FAILED", str(report_error))
                termination = self._termination_reason(research["id"])
                if termination:
                    self.store.update_research(research["id"], status="STOPPED",
                                               termination_reason=termination)
                    self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                            "RESEARCH TERMINATED", termination)
                    try:
                        final_paths = self.report_generator.generate(self.get_research(research["id"]))
                        self.store.append_event(
                            research["id"], EventKind.SYSTEM.value, "FINAL REPORT READY",
                            str(final_paths["markdown"]),
                            payload={key: str(value) for key, value in final_paths.items()},
                            source="REPORT_WRITER", event_type="REPORT_READY")
                    except Exception as report_error:
                        self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                                "FINAL REPORT FAILED", str(report_error))
                    if self.pi_runtime:
                        try:
                            self.pi_runtime.subagents.dispatch(
                                research["id"], "INDEPENDENT_REVIEWER",
                                "Audit whether the deterministic evidence supports the termination and conclusion.")
                            self.pi_runtime.subagents.dispatch(
                                research["id"], "REPORT_WRITER",
                                "Review the final deterministic report for evidence attribution and missing values.")
                        except Exception as dispatch_error:
                            self.store.append_event(
                                research["id"], EventKind.SYSTEM.value,
                                "SUBAGENT_DISPATCH_UNAVAILABLE",
                                f"终止评审子代理暂不可用（{dispatch_error}）；终止结论以确定性证据为准。")
                elif normalize_mode(current["mode"]) == "DEEP_OPTIMIZATION":
                    all_experiments = self.store.list_experiments(research["id"])
                    batch_round = max(
                        [int(item.get("round_number") or 0) for item in all_experiments]
                        + [int(current.get("current_round") or 0) + 1]
                    )
                    completed_items = [item for item in all_experiments
                                       if item.get("completed_at")
                                       and int(item.get("round_number") or 0) == batch_round]
                    completed_ids = [item["id"] for item in completed_items]
                    self.store.append_event(research["id"], EventKind.SYSTEM.value,
                                            "EXPERIMENT_BATCH_COMPLETED",
                                            f"Completed evidence batch: {completed_ids}")
                    refreshed = self.get_research(research["id"])
                    successful_items = [
                        item for item in completed_items
                        if item.get("status") == "SUCCESS"
                        and isinstance((item.get("result") or {}).get("objective", {}).get("compliance"), (int, float))
                    ]
                    best = self._select_round_best(successful_items)
                    failed_items = [item for item in completed_items if item.get("status") in {"FAILED", "CANCELLED"}]
                    weak_points: list[str] = []
                    if best:
                        quality = (best.get("result") or {}).get("quality", {})
                        if quality.get("connected_components") not in {None, 1}:
                            weak_points.append("连通分量约束未满足")
                        gray = quality.get("gray_ratio")
                        if isinstance(gray, (int, float)) and gray > float(refreshed.get("constraints", {}).get("gray_max", 0.05)):
                            weak_points.append("灰度率仍高于研究约束")
                    if failed_items:
                        weak_points.append(f"{len(failed_items)} 个候选求解无效，未产生可用于结论的真实指标")
                    comparison_reflection = "失败或取消方案只保留状态与原因，不以模拟指标补齐。"
                    self.store.append_event(
                        research["id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                        "已完成本轮真实结果比较。",
                        payload={
                            "workflow_step": "comparison", "status": "completed",
                            "experiment_ids": completed_ids, "evidence_ids": completed_ids,
                            "result": {
                                "successful": len(successful_items), "failed_or_cancelled": len(failed_items),
                            },
                            "reflection": comparison_reflection,
                            "next_action": "从真实成功结果中选择当前最优路线",
                        },
                        source="DETERMINISTIC_EVALUATOR",
                    )
                    self.store.append_event(
                        research["id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                        ("已对比本轮各候选的连通性、灰度率与柔度，选定最优方案 "
                         f"{best.get('id')}。" if best else "本轮没有有效求解结果，无法指定最优方案。"),
                        payload={
                            "workflow_step": "selection", "status": "completed",
                            "experiment_ids": completed_ids,
                            "evidence_ids": [best["id"]] if best else completed_ids,
                            "result": {
                                "best_experiment_id": best.get("id"),
                                "best_compliance": (best.get("result") or {}).get("objective", {}).get("compliance"),
                                "comparison": [
                                    {"id": item["id"],
                                     "compliance": (item.get("result") or {}).get("objective", {}).get("compliance"),
                                     "gray_ratio": (item.get("result") or {}).get("quality", {}).get("gray_ratio"),
                                     "connected_components": (item.get("result") or {}).get("quality", {}).get("connected_components")}
                                    for item in successful_items
                                ],
                            },
                            "reflection": ("优选顺序：结构连通优先，灰度率更低次之，柔度更低收尾；"
                                           "只使用同一 Research 中本轮持久化的真实成功结果。"),
                            "next_action": "把最优方案提交人工审批，作为下一阶段基线或重开一轮",
                        },
                        source="DETERMINISTIC_EVALUATOR",
                    )
                    self.store.append_event(
                        research["id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                        "已完成本轮问题诊断。",
                        payload={
                            "workflow_step": "diagnosis", "status": "completed",
                            "experiment_ids": completed_ids, "evidence_ids": completed_ids,
                            "result": {"weak_points": weak_points},
                            "reflection": "；".join(weak_points) if weak_points else "当前真实最优方案未触发连通性、灰度率或失败候选诊断项。",
                            "next_action": "基于诊断形成下一轮受控建议",
                        },
                        source="DETERMINISTIC_EVALUATOR",
                    )
                    self.store.append_event(
                        research["id"], EventKind.ANALYSIS.value, "WORKFLOW_ROUND_COMPLETED",
                        "本轮真实实验已完成比较、优选和问题诊断，正在形成下一轮建议。",
                        payload={
                            "workflow_step": "next_round", "status": "completed",
                            "experiment_ids": completed_ids,
                            "evidence_ids": completed_ids,
                            "best_experiment_id": best.get("id"),
                            "result": {
                                "best_compliance": (best.get("result") or {}).get("objective", {}).get("compliance"),
                                "successful": len(successful_items),
                                "failed": len(failed_items),
                            },
                            "reflection": "下一轮只依据本轮真实实验、已导入工程基线和已审计诊断提出建议；仍不自动批准或运行。",
                            "next_action": "由 Agent 基于诊断提出下一轮受控方案，仍需 Policy 与审批",
                        },
                        source="RESEARCH_ORCHESTRATOR",
                    )
                    fidelity_rank = {"STEP1": 0, "STEP2": 1, "STEP3": 2, "STEP4": 3}
                    completed_fidelities = [normalize_stage(item.get("fidelity"))
                                            for item in completed_items]
                    internal_fidelity = max(completed_fidelities,
                                            key=lambda value: fidelity_rank.get(value, 0), default="STEP1")
                    stage_code = internal_fidelity
                    self.store.append_event(
                        research["id"], EventKind.HUMAN.value, "FIDELITY_STAGE_AWAITING_DECISION",
                        f"{stage_code} 已完成，请确认进入下一流程，或在本流程再进行一轮。",
                        payload={
                            "stage_code": stage_code, "internal_fidelity": internal_fidelity,
                            "round": next_round, "experiment_ids": completed_ids,
                            "best_experiment_id": best.get("id"),
                            "result": {
                                "best_compliance": (best.get("result") or {}).get("objective", {}).get("compliance"),
                                "successful": len(successful_items), "failed": len(failed_items),
                                "weak_points": weak_points,
                            },
                        },
                        source="RESEARCH_ORCHESTRATOR",
                    )
                    self.store.update_research(research["id"], status="READY")
                elif current["status"] != "STOPPED":
                    self.store.update_research(research["id"], status="READY")

    def _persist_artifacts(self, research_id: str, experiment_id: str,
                           result: dict[str, Any]) -> dict[str, Any]:
        import numpy as np
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.font_manager import FontProperties
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        chinese_font = FontProperties(fname=str(font_path)) if font_path.is_file() else None
        directory = self.data_dir / research_id / "artifacts" / experiment_id
        directory.mkdir(parents=True, exist_ok=True)
        artifacts = result.setdefault("artifacts", {})
        density = np.asarray(artifacts.get("density"), dtype=float)
        density_path = directory / "density.npy"
        np.save(density_path, density)
        stress_value = artifacts.get("stress")
        stress_path = directory / "stress.npy"
        if stress_value is not None:
            stress = np.asarray(stress_value, dtype=float)
            if stress.shape == density.shape and np.isfinite(stress).all():
                np.save(stress_path, stress)
        history_path = directory / "history.json"
        history_path.write_text(json.dumps(artifacts.get("history", []), default=str), encoding="utf-8")
        solver_path = directory / "solver.json"
        solver_path.write_text(json.dumps(result.get("solver", {}), default=str), encoding="utf-8")
        log_path = directory / "log.txt"
        log_path.write_text(
            f"experiment={experiment_id}\nstatus={result.get('status')}\n"
            f"compliance={result.get('objective', {}).get('compliance')}\n"
            f"gray_ratio={result.get('quality', {}).get('gray_ratio')}\n"
            f"maximum_von_mises={result.get('quality', {}).get('maximum_von_mises')}\n"
            f"stress_unit={result.get('quality', {}).get('stress_unit')}\n", encoding="utf-8")
        vtk_path = directory / "density.vtk"
        self._write_density_vtk(vtk_path, density)
        topology_path = directory / "topology.png"
        if density.ndim == 3:
            from mpl_toolkits.mplot3d.art3d import Poly3DCollection
            research = self.get_research(research_id)
            configured = ((research.get("defaults") or {}).get("optimization_config") or {})
            dimensions = list(configured.get("dimensions") or
                              (research.get("geometry") or {}).get("dimensions") or
                              [density.shape[1], density.shape[0], density.shape[2]])
            while len(dimensions) < 3:
                dimensions.append(1.0)
            triangles = _density_surface_triangles(density, dimensions)
            figure = plt.figure(figsize=(7.2, 5.2), dpi=170, facecolor="white")
            axis = figure.add_subplot(111, projection="3d")
            if triangles:
                surface = Poly3DCollection(
                    triangles, facecolor="#aeb7c2", edgecolor="none",
                    linewidth=0, antialiased=True,
                )
                surface.set_rasterized(True)
                axis.add_collection3d(surface)
                axis.set_xlim(0, dimensions[0]); axis.set_ylim(0, dimensions[1]); axis.set_zlim(0, dimensions[2])
            else:
                axis.text2D(.5, .5, "No material above density threshold", ha="center", va="center",
                            transform=axis.transAxes)
            axis.view_init(elev=24, azim=-54)
            axis.set_box_aspect(tuple(max(float(value), 1e-12) for value in dimensions[:3]))
            axis.set_axis_off()
        else:
            figure, axis = plt.subplots(figsize=(7.2, 2.8), dpi=170, facecolor="white")
            axis.imshow(density, cmap="gray_r", vmin=0, vmax=1,
                        interpolation="nearest", aspect="equal")
            axis.set_axis_off()
        figure.tight_layout(); figure.savefig(topology_path, bbox_inches="tight",
                                               facecolor="white")
        plt.close(figure)
        stress_image_path = directory / "stress.png"
        if stress_path.is_file():
            stress = np.load(stress_path)
            if stress.ndim == 3:
                from mpl_toolkits.mplot3d.art3d import Poly3DCollection
                figure = plt.figure(figsize=(7.2, 5.2), dpi=170, facecolor="white")
                axis = figure.add_subplot(111, projection="3d")
                research = self.get_research(research_id)
                configured = ((research.get("defaults") or {}).get("optimization_config") or {})
                dimensions = list(configured.get("dimensions") or
                                  (research.get("geometry") or {}).get("dimensions") or
                                  [density.shape[1], density.shape[0], density.shape[2]])
                while len(dimensions) < 3:
                    dimensions.append(1.0)
                triangles = _density_surface_triangles(density, dimensions)
                span = max(float(np.max(stress) - np.min(stress)), 1e-12)
                rows, columns, layers = stress.shape
                colors = []
                for triangle in triangles:
                    center = np.mean(np.asarray(triangle, dtype=float), axis=0)
                    column = min(columns - 1, max(0, int(round(center[0] / dimensions[0] * columns - .5))))
                    row = min(rows - 1, max(0, int(round(center[1] / dimensions[1] * rows - .5))))
                    layer = min(layers - 1, max(0, int(round(center[2] / dimensions[2] * layers - .5))))
                    normalized = (float(stress[row, column, layer]) - float(np.min(stress))) / span
                    colors.append(plt.cm.gray(.25 + .65 * normalized))
                if triangles:
                    surface = Poly3DCollection(
                        triangles, facecolors=colors, edgecolor="none",
                        linewidth=0, antialiased=True,
                    )
                    surface.set_rasterized(True)
                    axis.add_collection3d(surface)
                    axis.set_xlim(0, dimensions[0]); axis.set_ylim(0, dimensions[1]); axis.set_zlim(0, dimensions[2])
                else:
                    axis.text2D(.5, .5, "No material above density threshold", ha="center", va="center",
                                transform=axis.transAxes)
                axis.view_init(elev=24, azim=-54)
                axis.set_box_aspect(tuple(max(float(value), 1e-12) for value in dimensions[:3]))
                axis.set_axis_off()
            else:
                figure, axis = plt.subplots(figsize=(7.2, 2.8), dpi=170, facecolor="white")
                axis.imshow(stress, cmap="gray", interpolation="nearest", aspect="equal")
                axis.set_axis_off()
            figure.tight_layout(); figure.savefig(stress_image_path, bbox_inches="tight",
                                                   facecolor="white")
            plt.close(figure)
        convergence_path = directory / "convergence.png"
        history = list(artifacts.get("history") or [])
        figure, axis = plt.subplots(figsize=(7.2, 3.2), dpi=150)
        iterations = [item.get("iteration") for item in history if item.get("compliance") is not None]
        compliance = [item.get("compliance") for item in history if item.get("compliance") is not None]
        if compliance:
            axis.plot(iterations, compliance, color="#111111", linewidth=1.8)
            if chinese_font:
                axis.set_xlabel("迭代", fontproperties=chinese_font)
                axis.set_ylabel("柔度", fontproperties=chinese_font)
            else:
                axis.set_xlabel("Iteration"); axis.set_ylabel("Compliance")
            axis.grid(color="#b8b8b8", alpha=.45)
        else:
            axis.text(.5, .5, "Not calculated", ha="center", va="center", transform=axis.transAxes)
            axis.set_axis_off()
        figure.tight_layout(); figure.savefig(convergence_path, bbox_inches="tight")
        plt.close(figure)
        artifacts.update({"density_path": str(density_path), "history_path": str(history_path),
                          "solver_output_path": str(solver_path), "log": str(log_path),
                          "vtk": str(vtk_path), "topology_image": str(topology_path),
                          "convergence_image": str(convergence_path)})
        parent_ids: list[str] = []
        stored_artifacts = [("DENSITY", density_path), ("HISTORY", history_path),
                                             ("SOLVER_EVIDENCE", solver_path), ("VTK", vtk_path),
                                             ("TOPOLOGY_IMAGE", topology_path),
                                             ("CONVERGENCE_IMAGE", convergence_path)]
        if stress_path.is_file():
            stored_artifacts.append(("STRESS", stress_path))
            stored_artifacts.append(("STRESS_IMAGE", stress_image_path))
            artifacts["stress_path"] = str(stress_path)
            artifacts["stress_image"] = str(stress_image_path)
        for artifact_type, artifact_path in stored_artifacts:
            artifact_id = f"AR-{uuid.uuid4().hex[:12].upper()}"
            self.store.create_artifact({
                "id": artifact_id, "research_id": research_id, "experiment_id": experiment_id,
                "artifact_type": artifact_type, "path": str(artifact_path),
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "parents": list(parent_ids),
                "metadata": {
                    "result_source": result.get("result_source", "LIVE_REAL_RUN"),
                    "shape": list(density.shape),
                    "dimension": int(density.ndim),
                    "rendering": "density-isosurface" if artifact_type == "TOPOLOGY_IMAGE" else None,
                    "surface_level": .5 if artifact_type == "TOPOLOGY_IMAGE" else None,
                    "stress_unit": result.get("quality", {}).get("stress_unit"),
                    "stress_unit_trusted": result.get("quality", {}).get("stress_unit_trusted"),
                },
            })
            if artifact_type == "STRESS":
                result.setdefault("quality", {})["stress_evidence_id"] = artifact_id
            parent_ids.append(artifact_id)
        artifacts["lineage_ids"] = parent_ids
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
        experiment_id = decision.get("experiment_id")
        lock = self._experiment_lock(experiment_id) if experiment_id else self._completion_lock
        with lock:
            decision = self._require_decision(decision_id)
            if decision["status"] != "PENDING":
                return decision
            if not self.store.resolve_decision_if_pending(decision_id, "APPROVED"):
                return self._require_decision(decision_id)
            decision = self._require_decision(decision_id)
            if experiment_id:
                self.store.update_experiment(experiment_id, human_decision="APPROVED")
            self.store.append_event(decision["research_id"], EventKind.HUMAN.value,
                                    "HUMAN APPROVAL", f"Approved {decision['intent']}.",
                                    experiment_id, {"decision_id": decision_id})
            if experiment_id:
                self.store.append_event(
                    decision["research_id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                    f"{experiment_id} 已通过人工审批边界。", experiment_id,
                    {
                        "workflow_step": "approval", "status": "completed",
                        "experiment_ids": [experiment_id], "evidence_ids": [decision_id],
                        "reflection": "审批只授权执行受控实验，不等同于确认方案有效或结果成功。",
                        "next_action": "执行真实实验并等待确定性评估",
                    },
                    source="HUMAN",
                )
        if experiment_id:
            self.run_experiment(experiment_id)
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
        experiment_id = decision.get("experiment_id")
        lock = self._experiment_lock(experiment_id) if experiment_id else self._completion_lock
        with lock:
            decision = self._require_decision(decision_id)
            if decision["status"] != "PENDING":
                return decision
            if not self.store.resolve_decision_if_pending(decision_id, "REJECTED"):
                return self._require_decision(decision_id)
            decision = self._require_decision(decision_id)
            experiment = self.store.get_experiment(experiment_id) if experiment_id else None
            if experiment and experiment["status"] == "WAITING":
                self.store.update_experiment(experiment_id, status="CANCELLED")
            if experiment:
                self.store.update_experiment(experiment_id, human_decision="REJECTED")
            self.store.append_event(decision["research_id"], EventKind.HUMAN.value,
                                    "HUMAN REJECTION", f"Rejected {decision['intent']}.",
                                    experiment_id, {"decision_id": decision_id})
            if experiment_id:
                self.store.append_event(
                    decision["research_id"], EventKind.ANALYSIS.value, "WORKFLOW_REFLECTION",
                    f"{experiment_id} 未通过人工审批，已作为取消方案保留。", experiment_id,
                    {
                        "workflow_step": "approval", "status": "completed",
                        "experiment_ids": [experiment_id], "evidence_ids": [decision_id],
                        "reflection": "该方案未执行，因此没有真实 FEM 指标；只保留拒绝事实，不补造结果。",
                        "next_action": "继续处理其余候选方案",
                    },
                    source="HUMAN",
                )
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
        research = self.stop_autonomous_research(research_id)
        return WorkspaceCommandResult(
            ok=True, message="Research stopping." if research["status"] == "STOPPING" else "Research stopped.",
            action="stop", data={"status": research["status"]},
        )

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
        labels = {step: stage_label(step) for step in FidelityManager.CODES}
        promoted = ExperimentCreate(purpose=f"Promote {source['id']} to {target}",
                                    fidelity=labels[target], mesh_level=FidelityManager.mesh_level(target),
                                    backend=FidelityManager.backend_for(target), parameters=source["parameters"],
                                    warm_start=source["id"], requires_approval=False,
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
        paths = self.report_generator.generate(research)
        self.store.append_event(
            research_id, EventKind.SYSTEM.value, "REPORT GENERATED", str(paths["markdown"]),
            payload={key: str(value) for key, value in paths.items()},
            source="REPORT_WRITER", event_type="REPORT_READY")
        return paths["markdown"]

    def export_report(self, research_id: str, *, name: str,
                      output_directory: str | Path,
                      formats: list[str], overwrite: bool = False) -> dict[str, Any]:
        research = self.get_research(research_id)
        paths = self.report_generator.export(
            research, name=name, output_directory=output_directory,
            formats=formats, overwrite=overwrite,
        )
        files = []
        for key in ("markdown", "pdf"):
            path = paths.get(key)
            if path and path.is_file():
                files.append({
                    "path": str(path), "sizeBytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        assets = paths["assets"]
        for path in sorted(assets.rglob("*")):
            if path.is_file():
                files.append({
                    "path": str(path), "sizeBytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                })
        payload = {
            "markdownPath": str(paths["markdown"]) if paths.get("markdown") else None,
            "pdfPath": str(paths["pdf"]) if paths.get("pdf") else None,
            "assetDirectory": str(assets),
            "files": files,
        }
        self.store.append_event(
            research_id, EventKind.SYSTEM.value, "REPORT EXPORTED",
            f"科研报告已导出至 {Path(output_directory).resolve()}",
            payload=payload, source="REPORT_WRITER", event_type="REPORT_READY",
        )
        return payload

    def generate_round_report(self, research_id: str, round_number: int) -> dict[str, str]:
        paths = self.report_generator.generate(self.get_research(research_id), round_number=round_number)
        return {key: str(value) for key, value in paths.items()}

    def report_path(self, research_id: str, kind: str = "markdown") -> Path:
        paths = self.report_generator.generate(self.get_research(research_id))
        return paths["pdf" if kind == "pdf" else "markdown"]

    def compare(self, research_id: str, experiment_ids: list[str]) -> list[dict[str, Any]]:
        values = []
        for experiment_id in experiment_ids:
            experiment = self.get_experiment(experiment_id)
            if experiment["research_id"] != research_id:
                raise ValueError("Experiment belongs to another research")
            values.append(experiment)
        return values

    def guide_research(self, research_id: str, text: str) -> dict[str, Any]:
        self._require_research(research_id)
        if not self.pi_runtime:
            entries = self.knowledge.search(text, self._require_research(research_id).get("locale", "zh-CN"), limit=5)
            return {"status": "KNOWLEDGE_ONLY", "task": None, "knowledge": entries,
                    "message": "Pi runtime is unavailable; offline guidance remains available."}
        task = self.pi_runtime.subagents.guide(research_id, text)
        return {"status": task["status"], "task": task}

    def preview_guidance(self, text: str, locale: str = "zh-CN") -> dict[str, Any]:
        lowered = text.lower()
        template = ("L-bracket" if any(token in lowered for token in ("l型", "l 型", "l-bracket")) else
                    "simply_supported" if any(token in lowered for token in ("简支", "simply")) else
                    "cantilever" if any(token in lowered for token in ("悬臂", "cantilever")) else
                    "bridge" if any(token in lowered for token in ("桥", "bridge")) else "MBB")
        dimension = 3 if any(token in lowered for token in ("3d", "三维", "立体")) else 2
        entries = self.knowledge.search(text, locale, limit=5)
        zh = locale == "zh-CN"
        questions = (["请确认结构尺寸和单位。", "请确认载荷方向、大小和作用区域。",
                      "请确认固定区域、体积分数和连通性要求。"] if zh else
                     ["Confirm dimensions and units.", "Confirm load direction, magnitude and region.",
                      "Confirm supports, volume fraction and connectivity requirement."])
        return {"source": "AI_SUGGESTED", "requires_confirmation": True,
                "suggestions": {"geometry": template, "dimension": dimension},
                "questions": questions, "knowledge": entries,
                "notice": ("这些建议尚未写入 Research Contract。" if zh else
                           "These suggestions are not yet part of the Research Contract.")}

    def solver_capabilities(self) -> dict[str, Any]:
        health = self.matlab_worker.health()
        runtime = self.matlab_worker.capabilities(probe=False)
        profiles = []
        for code, dimension, mesh, backend in (
            ("STEP1", 2, "coarse", "python"),
            ("STEP2", 2, "coarse", "python"),
            ("STEP3", 3, "coarse3d", "python3d"),
            ("STEP4", 3, "fine3d", "matlab"),
        ):
            profiles.append({
                "fidelity": code, "dimension": dimension, "mesh_level": mesh,
                "backend": backend,
                "available": True if backend != "matlab" else health.get("state") == "READY",
                "variants": runtime.get("variants", ["reference_cpu"]),
                "selected_variant": runtime.get("selected_variant", "reference_cpu"),
                "acceleration_mode": runtime.get("acceleration_mode", "cpu"),
                "requires_human_approval": False,
            })
        return {"matlab": health, "runtime": runtime, "fidelities": profiles,
                "strict_matlab": False, "python_fallback": True}

    def preview_geometry(self, request: dict[str, Any]) -> dict[str, Any]:
        """Generate masks and load/support node mappings inside controlled MATLAB."""
        return self.matlab_worker.preview_geometry(request)

    def matlab_health(self) -> dict[str, Any]:
        value = {**self.matlab_worker.health(), "capabilities": self.matlab_worker.capabilities(probe=False)}
        if value.get("state") == "AVAILABLE":
            value["state"] = "CONFIGURED"
        if self._matlab_restart["running"]:
            value["state"] = "STARTING"
        if self._matlab_restart["last_error"]:
            value["last_error"] = self._matlab_restart["last_error"]
        value["restart"] = dict(self._matlab_restart)
        return value

    def restart_matlab(self) -> dict[str, Any]:
        if not self._matlab_restart["running"]:
            self._matlab_restart = {"running": True, "last_error": None, "updated_at": utc_now()}
            threading.Thread(target=self._restart_matlab_job, name="matlab-mcp-restart", daemon=True).start()
        return self.matlab_health()

    def _restart_matlab_job(self) -> None:
        settings = self.get_settings()["compute"]
        error = None
        warmup = None
        try:
            self.matlab_worker.configure(matlab_root=settings.get("matlab_root"),
                                         timeout=settings["matlab_timeout_seconds"])
            # Cold-start the MCP process and MATLAB session and probe capabilities so
            # the first real experiment does not pay MATLAB startup latency.
            warmup = self.matlab_worker.warmup()
        except Exception as exc:
            error = str(exc)[:1000]
        self._matlab_restart = {"running": False, "last_error": error,
                                "warmup": warmup, "updated_at": utc_now()}

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
        research = self.create_research(ResearchCreate(name="Topology Optimization Workspace"))
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
