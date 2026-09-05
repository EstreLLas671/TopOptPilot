"""Headless, machine-readable command surface for TopOptPilot.

``topoptctl`` is deliberately a narrow client of the authenticated local
sidecar.  It is not a shell bridge and never accepts MATLAB code, arbitrary
file paths for solver output, a desktop bearer token, or an API key argument.
The daemon binds to loopback only; its short-lived token is kept in Windows
Credential Manager and is never serialized to a session file or terminal
output.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import click
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from topoptpilot.security.credentials import (
    delete_local_secret,
    get_local_secret,
    qwen_api_key_source,
    set_local_secret,
    set_qwen_api_key,
)
from topoptpilot_desktop.artifacts.models import SolverLane
from topoptpilot_desktop.engineering.runs import RunCreateRequest


CLI_SOURCE = "TOPoptctl"
DEFAULT_WAIT_SECONDS = 300.0
MAX_WAIT_SECONDS = 900.0
_SESSION_FILE = "headless-session.json"
_RUN_ID_RE = re.compile(r"^eng-[0-9a-f]{32}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_-]{1,160}$")
_MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")
_SENSITIVE_KEYS = {"api_key", "apikey", "authorization", "credential", "key", "password", "secret", "token"}
_INLINE_SECRET = re.compile(r"(?i)\b(?:sk|api)[_-][A-Za-z0-9._~+/=-]{12,}\b")


class TopoptCtlError(RuntimeError):
    """A safe, user-actionable error suitable for a machine envelope."""

    def __init__(self, code: str, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class CliGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nelx: int = Field(ge=1, le=2000)
    nely: int = Field(ge=1, le=2000)
    nelz: int | None = Field(default=None, ge=1, le=500)


class CliParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    volfrac: float = Field(gt=0, le=1)
    penal: float = Field(ge=1, le=5)
    rmin: float = Field(gt=0, le=100)
    min_iter: int = Field(default=1, ge=1, le=500)
    max_iter: int = Field(default=60, ge=1, le=500)
    filter_strategy: Literal["fixed", "adaptive"] = "fixed"
    accuracy: Literal["standard", "high"] = "standard"

    @model_validator(mode="after")
    def check_iteration_range(self) -> "CliParams":
        if self.min_iter > self.max_iter:
            raise ValueError("min_iter must not exceed max_iter")
        return self


class CliMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preset: Literal[
        "normalized", "structural-steel", "aluminum-6061-t6", "titanium-ti6al4v", "custom"
    ] = "normalized"
    name: str = Field(default="归一化参考材料", min_length=1, max_length=80)
    E: float | None = Field(default=None, gt=0)
    nu: float | None = Field(default=None, gt=-1, lt=0.5)
    density_kg_m3: float | None = Field(default=None, gt=0)
    yield_strength_MPa: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def check_custom_material(self) -> "CliMaterial":
        if self.preset == "custom" and any(
            value is None for value in (self.E, self.density_kg_m3, self.yield_strength_MPa)
        ):
            raise ValueError("custom material requires E, density_kg_m3 and yield_strength_MPa")
        return self


class CliEngineeringTask(BaseModel):
    """Strict, data-only Engineering task accepted by the headless CLI."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["2d", "3d"] = "2d"
    load_case: Literal["cantilever", "MBB", "simply_supported", "L-bracket"] = "cantilever"
    geometry: CliGeometry
    params: CliParams
    material: CliMaterial = Field(default_factory=CliMaterial)

    @model_validator(mode="after")
    def check_dimension_geometry(self) -> "CliEngineeringTask":
        if self.dimension == "2d" and self.geometry.nelz not in {None, 1}:
            raise ValueError("2d tasks must omit geometry.nelz or set it to 1")
        if self.dimension == "3d" and self.geometry.nelz is None:
            raise ValueError("3d tasks require geometry.nelz")
        return self


@dataclass(frozen=True)
class HeadlessSession:
    session_id: str
    pid: int
    port: int
    data_dir: Path
    started_at: str


@dataclass(frozen=True)
class CliState:
    data_dir: Path
    json_output: bool


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_dir() -> Path:
    configured = os.environ.get("TOPOPTPILOT_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    return (local / "TopOptPilot-Headless").resolve()


def _normalized_data_dir(value: str | Path) -> Path:
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise TopoptCtlError("INVALID_DATA_DIR", "data directory is not a directory")
    return path


def _session_path(data_dir: Path) -> Path:
    return data_dir / "headless" / _SESSION_FILE


def _secret_target(data_dir: Path) -> str:
    digest = hashlib.sha256(str(data_dir.resolve()).encode("utf-8")).hexdigest()
    return f"TopOptPilot/HeadlessSession/{digest}"


def session_public_payload(session: HeadlessSession) -> dict[str, Any]:
    """Metadata persisted in a local file; never add a token to this mapping."""
    return {
        "schemaVersion": 1,
        "sessionId": session.session_id,
        "pid": session.pid,
        "port": session.port,
        "dataDir": str(session.data_dir.resolve()),
        "startedAt": session.started_at,
    }


def _write_session(session: HeadlessSession) -> None:
    target = _session_path(session.data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(session_public_payload(session), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def _read_session(data_dir: Path) -> HeadlessSession | None:
    target = _session_path(data_dir)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
            return None
        session_id = raw.get("sessionId")
        pid = raw.get("pid")
        port = raw.get("port")
        started_at = raw.get("startedAt")
        declared_dir = Path(str(raw.get("dataDir", ""))).expanduser().resolve()
        if (
            not isinstance(session_id, str)
            or not _IDENTIFIER_RE.fullmatch(session_id)
            or isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid < 1
            or isinstance(port, bool)
            or not isinstance(port, int)
            or not 1 <= port <= 65535
            or not isinstance(started_at, str)
            or declared_dir != data_dir.resolve()
        ):
            return None
        return HeadlessSession(session_id, pid, port, data_dir.resolve(), started_at)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _clear_session(data_dir: Path) -> None:
    target = _session_path(data_dir)
    try:
        target.unlink()
    except FileNotFoundError:
        pass
    delete_local_secret(_secret_target(data_dir))


def parse_sidecar_banner(line: str) -> dict[str, Any]:
    prefix = "TOPPILOT_SIDECAR="
    if not isinstance(line, str) or not line.startswith(prefix):
        raise TopoptCtlError("SIDECAR_START_FAILED", "headless sidecar did not emit its startup banner")
    try:
        value = json.loads(line[len(prefix):])
    except json.JSONDecodeError as exc:
        raise TopoptCtlError("SIDECAR_START_FAILED", "headless sidecar emitted an invalid startup banner") from exc
    if not isinstance(value, dict):
        raise TopoptCtlError("SIDECAR_START_FAILED", "headless sidecar startup banner is invalid")
    port, token = value.get("port"), value.get("token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise TopoptCtlError("SIDECAR_START_FAILED", "headless sidecar returned an invalid loopback port")
    if not isinstance(token, str) or len(token) < 32:
        raise TopoptCtlError("SIDECAR_START_FAILED", "headless sidecar returned an invalid session token")
    return {"port": port, "token": token}


def _readline_with_timeout(stream, timeout: float) -> str | None:
    output: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            output.put(stream.readline())
        except (OSError, ValueError):
            output.put(None)

    threading.Thread(target=read, daemon=True).start()
    try:
        value = output.get(timeout=timeout)
    except queue.Empty:
        return None
    return value or None


def _is_pid_alive(pid: int) -> bool:
    if pid < 1:
        return False
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="mbcs",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.stdout is None:
            return False
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _is_our_sidecar_process(pid: int) -> bool:
    """Prevent a tampered stale session file from targeting an arbitrary PID."""
    if os.name != "nt":
        return False
    command = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "$p=Get-CimInstance Win32_Process -Filter \"ProcessId = " + str(pid)
        + "\" -ErrorAction SilentlyContinue; if ($p) { $p.CommandLine }"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, UnicodeError):
        return False
    return "topoptpilot_desktop.api.desktop_sidecar" in completed.stdout


def _terminate_sidecar(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class HttpApiClient:
    """Minimal authenticated JSON client for the loopback sidecar only."""

    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0) -> None:
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            raise TopoptCtlError("INVALID_SIDECAR_URL", "topoptctl only connects to a 127.0.0.1 HTTP sidecar")
        if not token:
            raise TopoptCtlError("MISSING_SESSION_TOKEN", "headless daemon session token is unavailable")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> bytes:
        if not path.startswith("/") or path.startswith("//"):
            raise TopoptCtlError("INVALID_API_PATH", "invalid TopOptPilot API path")
        body = None
        headers = {"Accept": "application/json", "X-TopOptPilot-Token": self.token}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            detail: Any = None
            try:
                detail = json.loads(exc.read().decode("utf-8", errors="replace")).get("detail")
            except (ValueError, AttributeError, OSError):
                detail = None
            raise TopoptCtlError("API_ERROR", f"TopOptPilot sidecar returned HTTP {exc.code}", details=detail) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TopoptCtlError("SIDECAR_UNAVAILABLE", "TopOptPilot headless sidecar is unavailable") from exc

    def request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        raw = self._request(method, path, payload)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise TopoptCtlError("INVALID_API_RESPONSE", "TopOptPilot sidecar returned invalid JSON") from exc

    def download(self, path: str) -> bytes:
        return self._request("GET", path)


def _client_for_session(session: HeadlessSession) -> HttpApiClient:
    token = get_local_secret(_secret_target(session.data_dir))
    if not token:
        raise TopoptCtlError("MISSING_SESSION_TOKEN", "headless daemon token is unavailable; start a fresh daemon")
    client = HttpApiClient(f"http://127.0.0.1:{session.port}", token)
    identity = client.request_json("GET", "/api/headless/session")
    if not isinstance(identity, dict) or identity.get("sessionId") != session.session_id:
        raise TopoptCtlError("SESSION_IDENTITY_MISMATCH", "headless session identity could not be verified")
    return client


def _active_client(data_dir: Path) -> tuple[HeadlessSession, HttpApiClient]:
    session = _read_session(data_dir)
    if session is None:
        raise TopoptCtlError("DAEMON_NOT_RUNNING", "no valid headless daemon session was found; run `topoptctl daemon start`")
    return session, _client_for_session(session)


def start_headless_daemon(data_dir: Path, *, startup_timeout: float = 20.0) -> HeadlessSession:
    data_dir = _normalized_data_dir(data_dir)
    existing = _read_session(data_dir)
    if existing is not None:
        try:
            _client_for_session(existing)
        except TopoptCtlError:
            if _is_pid_alive(existing.pid):
                raise TopoptCtlError("DAEMON_SESSION_CONFLICT", "a recorded daemon is alive but cannot be verified; refuse to replace it")
            _clear_session(data_dir)
        else:
            raise TopoptCtlError("DAEMON_ALREADY_RUNNING", "a verified headless daemon is already running")

    session_id = "headless-" + uuid.uuid4().hex
    environment = os.environ.copy()
    environment.pop("TOPPILOT_DESKTOP_TOKEN", None)
    environment.update({
        "TOPOPTPILOT_DATA_DIR": str(data_dir),
        "TOPPILOT_DATA_DIR": str(data_dir),
        "TOPPILOT_RESOURCE_ROOT": str(project_root()),
        "TOPPILOT_HEADLESS_SESSION_ID": session_id,
    })
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [sys.executable, "-m", "topoptpilot_desktop.api.desktop_sidecar"],
        cwd=project_root(),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=flags,
    )
    try:
        assert process.stdout is not None
        line = _readline_with_timeout(process.stdout, startup_timeout)
        if line is None:
            raise TopoptCtlError("SIDECAR_START_TIMEOUT", "headless sidecar did not start within the allowed time")
        banner = parse_sidecar_banner(line.strip())
        session = HeadlessSession(
            session_id=session_id,
            pid=process.pid,
            port=banner["port"],
            data_dir=data_dir,
            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        set_local_secret(_secret_target(data_dir), banner["token"], username="TOPPILOT_HEADLESS_TOKEN")
        _write_session(session)
        _client_for_session(session)
        return session
    except Exception:
        _terminate_sidecar(process)
        try:
            _clear_session(data_dir)
        except OSError:
            pass
        raise


def stop_headless_daemon(data_dir: Path) -> HeadlessSession:
    data_dir = _normalized_data_dir(data_dir)
    session = _read_session(data_dir)
    if session is None:
        raise TopoptCtlError("DAEMON_NOT_RUNNING", "no valid headless daemon session was found")
    # First prove the port/token belongs to this session, then prove the PID is
    # the expected Python module before terminating its process tree.
    _client_for_session(session)
    if not _is_our_sidecar_process(session.pid):
        raise TopoptCtlError("DAEMON_PROCESS_MISMATCH", "recorded PID is not a TopOptPilot headless sidecar; refuse to terminate it")
    completed = subprocess.run(
        ["taskkill", "/PID", str(session.pid), "/T", "/F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) if os.name == "nt" else None
    if os.name != "nt":
        os.kill(session.pid, signal.SIGTERM)
    if os.name == "nt" and (completed is None or completed.returncode != 0) and _is_pid_alive(session.pid):
        raise TopoptCtlError("DAEMON_STOP_FAILED", "headless sidecar process tree could not be terminated")
    deadline = time.monotonic() + 5
    while _is_pid_alive(session.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _is_pid_alive(session.pid):
        raise TopoptCtlError("DAEMON_STOP_TIMEOUT", "headless sidecar process did not exit in time")
    _clear_session(data_dir)
    return session


def build_engineering_request(
    task: CliEngineeringTask,
    *,
    owner_id: str,
    time_limit: float | None = None,
) -> dict[str, Any]:
    if not _IDENTIFIER_RE.fullmatch(owner_id.replace(":", "_")) or len(owner_id) > 160:
        raise TopoptCtlError("INVALID_OWNER", "engineering owner id is invalid")
    payload: dict[str, Any] = {
        "lane": SolverLane.LOCAL_MATLAB.value,
        "ownerId": owner_id,
        "task": task.model_dump(mode="json", exclude_none=True),
    }
    if time_limit is not None:
        if not 0.1 <= time_limit <= MAX_WAIT_SECONDS:
            raise TopoptCtlError("INVALID_TIME_LIMIT", f"time limit must be between 0.1 and {int(MAX_WAIT_SECONDS)} seconds")
        payload["timeLimit"] = float(time_limit)
    # Reuse the server request model so the CLI can never manufacture a
    # payload that the desktop/API would reject differently.
    return RunCreateRequest.model_validate(payload).model_dump(by_alias=True, mode="json", exclude_none=True)


def _validate_identifier(value: str, label: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise TopoptCtlError("INVALID_IDENTIFIER", f"{label} is invalid")
    return value


def _validate_run_id(value: str) -> str:
    if not _RUN_ID_RE.fullmatch(value):
        raise TopoptCtlError("INVALID_RUN_ID", "run id is invalid")
    return value


def _load_task(path: Path) -> CliEngineeringTask:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TopoptCtlError("INVALID_TASK_FILE", "task file must be readable UTF-8 JSON") from exc
    try:
        return CliEngineeringTask.model_validate(raw)
    except ValidationError as exc:
        raise TopoptCtlError("INVALID_TASK", "task is outside the strict topoptctl schema", details=exc.errors()) from exc


def _task_from_project_config(config: dict[str, Any]) -> CliEngineeringTask:
    material = dict(config.get("material") or {})
    raw = {
        "dimension": config.get("dimension"),
        "load_case": config.get("bcType"),
        "geometry": {
            "nelx": config.get("nelx"),
            "nely": config.get("nely"),
            "nelz": config.get("nelz") if config.get("dimension") == "3d" else None,
        },
        "params": {
            "volfrac": config.get("volfrac"),
            "penal": config.get("penal"),
            "rmin": config.get("rmin"),
            "min_iter": config.get("minIterations"),
            "max_iter": config.get("maxIterations"),
            "filter_strategy": config.get("filterStrategy"),
            "accuracy": config.get("accuracy"),
        },
        "material": {
            "preset": material.get("preset", "normalized"),
            "name": material.get("name", "归一化参考材料"),
            "E": material.get("youngsModulusGPa"),
            "nu": material.get("poissonRatio"),
            "density_kg_m3": material.get("densityKgM3"),
            "yield_strength_MPa": material.get("yieldStrengthMPa"),
        },
    }
    try:
        return CliEngineeringTask.model_validate(raw)
    except ValidationError as exc:
        raise TopoptCtlError("PROJECT_CONFIG_INCOMPATIBLE", "project optimization config is not compatible with the engineering CLI schema", details=exc.errors()) from exc


def propose_policy_intent(
    client: HttpApiClient,
    *,
    research_id: str,
    intent: str,
    preserve: list[str],
    factor: str | None,
    source_experiment: str | None,
) -> Any:
    research_id = _validate_identifier(research_id, "research id")
    if intent not in {
        "ESTABLISH_BASELINE", "EXPLORE_PARAMETER", "REDUCE_GRAYNESS", "RESTORE_CONNECTIVITY",
        "TEST_COMPETING_EXPLANATIONS", "UPGRADE_FIDELITY", "VERIFY_CANDIDATE",
    }:
        raise TopoptCtlError("INVALID_INTENT", "intent is not in the Policy allowlist")
    # AGENTS.md requires context refresh before scientific interpretation.  It
    # is intentionally unconditional even if an external agent calls twice.
    client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "research_get_context",
        "arguments": {},
        "source": CLI_SOURCE,
    })
    arguments: dict[str, Any] = {"intent": intent, "preserve": preserve}
    if factor is not None:
        arguments["factor"] = factor
    if source_experiment is not None:
        arguments["source_experiment"] = _validate_identifier(source_experiment, "source experiment id")
    return client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "policy_compile_intent",
        "arguments": arguments,
        "source": CLI_SOURCE,
    })


def redact_for_output(value: Any) -> Any:
    """Defence-in-depth output redaction for JSON, errors and diagnostic text."""
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower().replace("-", "_") in _SENSITIVE_KEYS
            else redact_for_output(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_for_output(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_output(item) for item in value]
    if isinstance(value, str):
        return _INLINE_SECRET.sub("[REDACTED]", value)
    return value


def _doctor_settings_summary(settings: Any) -> dict[str, Any]:
    """Select only non-secret, actionable setup fields for the doctor command."""
    if not isinstance(settings, dict):
        return {"status": "invalid-settings-response"}
    agent = settings.get("agent")
    compute = settings.get("compute")
    return {
        "agent": {
            "model": agent.get("model") if isinstance(agent, dict) else None,
            "baseUrl": agent.get("base_url") if isinstance(agent, dict) else None,
            "safeMode": agent.get("safe_mode") if isinstance(agent, dict) else None,
            "credentialSource": settings.get("api_key_status"),
        },
        "compute": {
            "matlabRoot": compute.get("matlab_root") if isinstance(compute, dict) else None,
            "matlabTimeoutSeconds": (
                compute.get("matlab_timeout_seconds") if isinstance(compute, dict) else None
            ),
        },
    }


def collect_doctor_report(
    client: HttpApiClient,
    session: HeadlessSession,
    *,
    probe_matlab: bool,
    check_qwen: bool,
) -> dict[str, Any]:
    """Collect bounded diagnostics without starting a solver by default.

    A MATLAB discovery refresh can invoke a short executable probe and a Qwen
    check makes one model-health request. Both are opt-in so a plain doctor
    call is read-only with respect to external compute and model services.
    """
    service_health = client.request_json("GET", "/api/health")
    settings = client.request_json("GET", "/api/settings")
    engineering_health = client.request_json("GET", "/api/engineering/health")
    environment = client.request_json(
        "POST" if probe_matlab else "GET",
        "/api/engineering/environment/refresh" if probe_matlab else "/api/engineering/environment",
    )
    qwen = client.request_json("POST", "/api/settings/test-agent") if check_qwen else {
        "status": "not-checked",
        "reason": "pass --check-qwen to make a live provider request",
    }
    performed: list[str] = []
    if probe_matlab:
        performed.append("matlab-discovery-probe")
    if check_qwen:
        performed.append("qwen-connection-check")
    return {
        "sideEffect": "external-probes" if performed else "none",
        "performed": performed,
        "daemon": session_public_payload(session),
        "service": service_health,
        "settings": _doctor_settings_summary(settings),
        "engineering": {
            "health": engineering_health,
            "environment": environment,
        },
        "qwen": qwen,
        "policyBoundary": "diagnostic only; no engineering run or Policy experiment was submitted",
    }


def render_output(value: Any, *, json_output: bool) -> str:
    """Serialize already-safe output for machines or an interactive terminal."""
    if json_output:
        # Machine output must survive cmd.exe, Windows PowerShell, PowerShell 7
        # and remote Agent transports with different native code pages. JSON
        # Unicode escapes remain lossless after any standards-compliant parser.
        return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _emit(ctx: click.Context, value: Any) -> None:
    state: CliState = ctx.obj
    click.echo(render_output(redact_for_output(value), json_output=state.json_output))


def _success(ctx: click.Context, data: Any, **extra: Any) -> None:
    _emit(ctx, {"ok": True, "data": data, **extra})


def _api_error_payload(exc: TopoptCtlError) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
    if exc.details is not None:
        payload["error"]["details"] = exc.details
    return payload


def _require_confirm(confirm: bool, action: str) -> None:
    if not confirm:
        raise TopoptCtlError("CONFIRMATION_REQUIRED", f"{action} requires the explicit --confirm flag")


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--data-dir", type=click.Path(file_okay=False, path_type=Path), default=default_data_dir, show_default=True)
@click.option("--json/--human", "json_output", default=True, show_default=True,
              help="Emit a stable JSON envelope for external agents (default).")
@click.pass_context
def cli(ctx: click.Context, data_dir: Path, json_output: bool) -> None:
    """Use TopOptPilot safely without opening the desktop application."""
    ctx.obj = CliState(_normalized_data_dir(data_dir), json_output)


@cli.group()
def daemon() -> None:
    """Manage the loopback-only authenticated headless sidecar."""


@daemon.command("start")
@click.option("--startup-timeout", type=click.FloatRange(1, 60), default=20.0, show_default=True)
@click.pass_context
def daemon_start(ctx: click.Context, startup_timeout: float) -> None:
    session = start_headless_daemon(ctx.obj.data_dir, startup_timeout=startup_timeout)
    _success(ctx, session_public_payload(session), status="started")


@daemon.command("status")
@click.pass_context
def daemon_status(ctx: click.Context) -> None:
    session = _read_session(ctx.obj.data_dir)
    if session is None:
        _success(ctx, {"status": "stopped"})
        return
    try:
        client = _client_for_session(session)
        health = client.request_json("GET", "/api/health")
    except TopoptCtlError as exc:
        _success(ctx, {"status": "unverified", "session": session_public_payload(session), "reason": exc.code})
        return
    _success(ctx, {"status": "running", "session": session_public_payload(session), "health": health})


@daemon.command("stop")
@click.option("--confirm", is_flag=True, help="Explicitly terminate the verified headless sidecar process tree.")
@click.pass_context
def daemon_stop(ctx: click.Context, confirm: bool) -> None:
    _require_confirm(confirm, "daemon stop")
    session = stop_headless_daemon(ctx.obj.data_dir)
    _success(ctx, session_public_payload(session), status="stopped")


@cli.command("doctor")
@click.option(
    "--probe-matlab",
    is_flag=True,
    help="Refresh MATLAB discovery and permit its explicit executable probe; never starts a solver.",
)
@click.option(
    "--check-qwen",
    is_flag=True,
    help="Make one live Qwen-compatible health request using the locally stored credential.",
)
@click.pass_context
def doctor(ctx: click.Context, probe_matlab: bool, check_qwen: bool) -> None:
    """Report headless, Qwen and MATLAB readiness without opening the desktop UI."""
    session, client = _active_client(ctx.obj.data_dir)
    report = collect_doctor_report(
        client,
        session,
        probe_matlab=probe_matlab,
        check_qwen=check_qwen,
    )
    _success(ctx, report, status="diagnosed")


@cli.group("configure")
def configure() -> None:
    """Configure non-secret MATLAB and Qwen connection settings."""


@configure.command("matlab")
@click.option("--root", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True)
@click.pass_context
def configure_matlab(ctx: click.Context, root: Path) -> None:
    _, client = _active_client(ctx.obj.data_dir)
    settings = client.request_json("PATCH", "/api/settings", {"settings": {"compute": {"matlab_root": str(root.resolve())}}})
    # Force a fresh engineering discovery.  This probes the configured binary;
    # a successful save alone is not a claim that MATLAB is runnable.
    environment = client.request_json("POST", "/api/engineering/environment/refresh")
    _success(ctx, {"settings": settings.get("compute", {}), "engineeringEnvironment": environment})


@configure.command("qwen")
@click.option("--base-url", required=True, type=str)
@click.option("--model", required=True, type=str)
@click.option("--restart-pi", is_flag=True, help="Restart idle Pi RPC state to apply the changed model settings.")
@click.pass_context
def configure_qwen(ctx: click.Context, base_url: str, model: str, restart_pi: bool) -> None:
    endpoint = urllib.parse.urlparse(base_url.strip())
    if endpoint.scheme != "https" or not endpoint.netloc or endpoint.username or endpoint.password:
        raise TopoptCtlError("INVALID_QWEN_URL", "Qwen base URL must be an HTTPS URL without embedded credentials")
    if not _MODEL_RE.fullmatch(model):
        raise TopoptCtlError("INVALID_QWEN_MODEL", "Qwen model id contains unsupported characters")
    _, client = _active_client(ctx.obj.data_dir)
    settings = client.request_json("PATCH", "/api/settings", {"settings": {"agent": {"base_url": base_url.rstrip("/"), "model": model}}})
    pi = client.request_json("POST", "/api/settings/restart-pi") if restart_pi else None
    _success(ctx, {
        "agent": settings.get("agent", {}),
        "credentialSource": settings.get("api_key_status"),
        "pi": pi,
        "restartRequired": not restart_pi,
    })


@configure.command("qwen-key")
@click.option(
    "--stdin",
    "read_stdin",
    is_flag=True,
    help="Read the credential from standard input only; never use a command-line argument.",
)
@click.pass_context
def configure_qwen_key(ctx: click.Context, read_stdin: bool) -> None:
    """Store a Qwen credential in Windows Credential Manager without printing it."""
    if not read_stdin:
        raise TopoptCtlError(
            "SECRET_INPUT_REQUIRED",
            "Qwen credentials are accepted only through standard input; pass --stdin",
        )
    # Read a bounded value so an accidental binary stream cannot exhaust the
    # CLI process. The credential API applies the final 2048-character limit.
    supplied = sys.stdin.read(2049).strip()
    if not supplied:
        raise TopoptCtlError("EMPTY_SECRET", "Qwen credential input was empty")
    try:
        set_qwen_api_key(supplied)
    except (OSError, RuntimeError, ValueError) as exc:
        raise TopoptCtlError("CREDENTIAL_STORE_FAILED", "could not store the Qwen credential") from exc
    _success(ctx, {
        "credentialStored": True,
        "credentialSource": qwen_api_key_source(),
        "nextStep": "run topoptctl configure qwen-check to make an explicit live provider check",
    })


@configure.command("qwen-check")
@click.pass_context
def configure_qwen_check(ctx: click.Context) -> None:
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", "/api/settings/test-agent")
    _success(ctx, result)


@cli.group("project")
def project() -> None:
    """Create and configure policy-aware TopOptPilot research projects."""


@project.command("create")
@click.option("--name", required=True, type=str)
@click.option("--goal", required=True, type=str)
@click.option("--budget", type=click.IntRange(1, 10000), default=12, show_default=True)
@click.pass_context
def project_create(ctx: click.Context, name: str, goal: str, budget: int) -> None:
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", "/api/research", {
        "name": name,
        "goal": goal,
        "budget_total": budget,
        "mode": "COPILOT",
        "geometry": {"dimension": "2d"},
    })
    _success(ctx, result)


@project.command("show")
@click.argument("research_id")
@click.pass_context
def project_show(ctx: click.Context, research_id: str) -> None:
    research_id = _validate_identifier(research_id, "research id")
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("GET", f"/api/research/{urllib.parse.quote(research_id, safe='')}"))


@project.command("set-config")
@click.argument("research_id")
@click.option("--config", "config_path", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_context
def project_set_config(ctx: click.Context, research_id: str, config_path: Path) -> None:
    research_id = _validate_identifier(research_id, "research id")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TopoptCtlError("INVALID_PROJECT_CONFIG", "project config must be readable UTF-8 JSON") from exc
    if not isinstance(config, dict):
        raise TopoptCtlError("INVALID_PROJECT_CONFIG", "project config must be a JSON object")
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("PUT", f"/api/researches/{urllib.parse.quote(research_id, safe='')}/optimization-config", config)
    _success(ctx, result)


@cli.group("engineering")
def engineering() -> None:
    """Run a bounded engineering baseline; it is not a formal Policy experiment."""


def _plan_task(ctx: click.Context, config_path: Path | None, project_id: str | None, time_limit: float | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if bool(config_path) == bool(project_id):
        raise TopoptCtlError("TASK_SOURCE_REQUIRED", "provide exactly one of --config or --project")
    _, client = _active_client(ctx.obj.data_dir)
    if config_path is not None:
        task = _load_task(config_path)
        owner = "topoptctl-engineering"
    else:
        assert project_id is not None
        project_id = _validate_identifier(project_id, "project id")
        config = client.request_json("GET", f"/api/researches/{urllib.parse.quote(project_id, safe='')}/optimization-config")
        task = _task_from_project_config(config)
        owner = f"topoptctl:{project_id}"
    request = build_engineering_request(task, owner_id=owner, time_limit=time_limit)
    validated = client.request_json("POST", "/api/engineering/runs/validate", request)
    return request, validated


@engineering.command("plan")
@click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--project", "project_id", type=str)
@click.option("--time-limit", type=click.FloatRange(0.1, MAX_WAIT_SECONDS), default=None)
@click.pass_context
def engineering_plan(ctx: click.Context, config_path: Path | None, project_id: str | None, time_limit: float | None) -> None:
    request, validated = _plan_task(ctx, config_path, project_id, time_limit)
    _success(ctx, {
        "status": "validated",
        "request": request,
        "validated": validated,
        "policyBoundary": "engineering-baseline-only; import a completed run before Policy research",
    })


@engineering.group("run")
def engineering_run() -> None:
    """Start, inspect, wait for or cancel a controlled Engineering run."""


@engineering_run.command("start")
@click.option("--config", "config_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--project", "project_id", type=str)
@click.option("--time-limit", type=click.FloatRange(0.1, MAX_WAIT_SECONDS), default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--confirm", is_flag=True, help="Explicitly start local MATLAB after successful validation.")
@click.pass_context
def engineering_run_start(ctx: click.Context, config_path: Path | None, project_id: str | None, time_limit: float, confirm: bool) -> None:
    request, validated = _plan_task(ctx, config_path, project_id, time_limit)
    _require_confirm(confirm, "engineering run start")
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", "/api/engineering/runs", request)
    _success(ctx, {
        "run": result,
        "validated": validated,
        "policyBoundary": "engineering-baseline-only; this is not a formal Policy experiment",
    }, status="submitted")


@engineering_run.command("get")
@click.argument("run_id")
@click.pass_context
def engineering_run_get(ctx: click.Context, run_id: str) -> None:
    run_id = _validate_run_id(run_id)
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("GET", f"/api/engineering/runs/{run_id}"))


@engineering_run.command("events")
@click.argument("run_id")
@click.option("--after", "after_seq", type=click.IntRange(0), default=0, show_default=True)
@click.pass_context
def engineering_run_events(ctx: click.Context, run_id: str, after_seq: int) -> None:
    run_id = _validate_run_id(run_id)
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("GET", f"/api/engineering/runs/{run_id}/events?after_seq={after_seq}"))


@engineering_run.command("wait")
@click.argument("run_id")
@click.option("--timeout", type=click.FloatRange(0.1, MAX_WAIT_SECONDS), default=DEFAULT_WAIT_SECONDS, show_default=True)
@click.option("--interval", type=click.FloatRange(0.05, 10), default=0.5, show_default=True)
@click.pass_context
def engineering_run_wait(ctx: click.Context, run_id: str, timeout: float, interval: float) -> None:
    run_id = _validate_run_id(run_id)
    _, client = _active_client(ctx.obj.data_dir)
    deadline = time.monotonic() + timeout
    latest: Any = None
    while time.monotonic() < deadline:
        latest = client.request_json("GET", f"/api/engineering/runs/{run_id}")
        if isinstance(latest, dict) and latest.get("status") in {"completed", "failed", "cancelled"}:
            events = client.request_json("GET", f"/api/engineering/runs/{run_id}/events")
            _success(ctx, {"run": latest, "events": events.get("events", []) if isinstance(events, dict) else events})
            return
        time.sleep(interval)
    _success(ctx, {"run": latest, "timeoutSeconds": timeout}, status="timeout")
    raise click.exceptions.Exit(3)


@engineering_run.command("cancel")
@click.argument("run_id")
@click.option("--confirm", is_flag=True, help="Explicitly cancel the controlled run and its MATLAB process tree.")
@click.pass_context
def engineering_run_cancel(ctx: click.Context, run_id: str, confirm: bool) -> None:
    run_id = _validate_run_id(run_id)
    _require_confirm(confirm, "engineering run cancellation")
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("POST", f"/api/engineering/runs/{run_id}/cancel"), status="cancellation-requested")


def _safe_relative_artifact_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise TopoptCtlError("INVALID_ARTIFACT_PATH", "server returned an invalid artifact path")
    return path


@engineering.command("export")
@click.argument("run_id")
@click.option("--output-dir", type=click.Path(exists=True, file_okay=False, path_type=Path), required=True)
@click.option("--with-report/--no-report", default=True, show_default=True)
@click.pass_context
def engineering_export(ctx: click.Context, run_id: str, output_dir: Path, with_report: bool) -> None:
    run_id = _validate_run_id(run_id)
    destination_root = output_dir.resolve()
    if not destination_root.is_dir():
        raise TopoptCtlError("INVALID_EXPORT_DIR", "export directory does not exist")
    _, client = _active_client(ctx.obj.data_dir)
    run = client.request_json("GET", f"/api/engineering/runs/{run_id}")
    if not isinstance(run, dict) or run.get("status") not in {"completed", "failed", "cancelled"}:
        raise TopoptCtlError("RUN_NOT_TERMINAL", "only a terminal engineering run can be exported")
    if with_report:
        client.request_json("POST", f"/api/engineering/runs/{run_id}/report", {"name": "topoptctl-report"})
        run = client.request_json("GET", f"/api/engineering/runs/{run_id}")
    target = destination_root / f"topoptpilot-{run_id}"
    try:
        target.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise TopoptCtlError("EXPORT_EXISTS", f"export destination already exists: {target.name}") from exc
    copied: list[dict[str, Any]] = []
    try:
        references = [*(run.get("files") or []), *(run.get("snapshots") or [])]
        seen: set[str] = set()
        for reference in references:
            if not isinstance(reference, dict):
                continue
            relative = _safe_relative_artifact_path(str(reference.get("relativePath", "")))
            relative_text = relative.as_posix()
            if relative_text in seen:
                continue
            seen.add(relative_text)
            expected_hash = reference.get("sha256")
            if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                raise TopoptCtlError("INVALID_ARTIFACT_HASH", "server returned an invalid artifact hash")
            payload = client.download(f"/api/engineering/runs/{run_id}/files/{urllib.parse.quote(relative_text, safe='/')}")
            actual_hash = hashlib.sha256(payload).hexdigest()
            if actual_hash != expected_hash:
                raise TopoptCtlError("ARTIFACT_INTEGRITY_FAILED", f"artifact hash mismatch: {relative_text}")
            file_target = (target / Path(*relative.parts)).resolve()
            if target.resolve() not in file_target.parents:
                raise TopoptCtlError("INVALID_ARTIFACT_PATH", "artifact export escaped its destination")
            file_target.parent.mkdir(parents=True, exist_ok=True)
            file_target.write_bytes(payload)
            copied.append({"relativePath": relative_text, "sha256": actual_hash, "sizeBytes": len(payload)})
    except Exception:
        # Do not recursively delete a user-selected destination.  A partial
        # export remains explicit evidence for diagnosis rather than hiding it.
        raise
    manifest = {"schemaVersion": 1, "run": redact_for_output(run), "artifacts": copied}
    (target / "export-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    _success(ctx, {"runId": run_id, "exportDirectory": str(target), "artifacts": copied})


@cli.group("research")
def research() -> None:
    """Use only the allowlisted Policy workflow for formal research actions."""


@research.command("from-engineering-run")
@click.argument("run_id")
@click.option("--name", required=True, type=str)
@click.option("--goal", required=True, type=str)
@click.option("--budget", type=click.IntRange(1, 10000), default=12, show_default=True)
@click.pass_context
def research_from_engineering_run(ctx: click.Context, run_id: str, name: str, goal: str, budget: int) -> None:
    run_id = _validate_run_id(run_id)
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", f"/api/research/from-engineering-run/{run_id}", {
        "name": name,
        "goal": goal,
        "budgetTotal": budget,
    })
    _success(ctx, result, policyBoundary="completed engineering evidence linked; no Policy experiment was submitted")


@research.command("context")
@click.argument("research_id")
@click.pass_context
def research_context(ctx: click.Context, research_id: str) -> None:
    research_id = _validate_identifier(research_id, "research id")
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "research_get_context",
        "arguments": {},
        "source": CLI_SOURCE,
    })
    _success(ctx, result)


@research.command("propose")
@click.argument("research_id")
@click.option("--intent", required=True, type=str)
@click.option("--preserve", multiple=True, type=str)
@click.option("--factor", type=str)
@click.option("--source-experiment", type=str)
@click.pass_context
def research_propose(ctx: click.Context, research_id: str, intent: str, preserve: tuple[str, ...], factor: str | None, source_experiment: str | None) -> None:
    _, client = _active_client(ctx.obj.data_dir)
    result = propose_policy_intent(
        client, research_id=research_id, intent=intent, preserve=list(preserve),
        factor=factor, source_experiment=source_experiment,
    )
    _success(ctx, result)


@research.command("preview")
@click.argument("research_id")
@click.argument("proposal_id")
@click.pass_context
def research_preview(ctx: click.Context, research_id: str, proposal_id: str) -> None:
    research_id = _validate_identifier(research_id, "research id")
    proposal_id = _validate_identifier(proposal_id, "proposal id")
    _, client = _active_client(ctx.obj.data_dir)
    result = client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "experiment_preview",
        "arguments": {"proposal_id": proposal_id},
        "source": CLI_SOURCE,
    })
    _success(ctx, result)


@research.command("submit")
@click.argument("research_id")
@click.argument("proposal_id")
@click.option("--confirm", is_flag=True, help="Explicitly submit the already Policy-compiled proposal.")
@click.pass_context
def research_submit(ctx: click.Context, research_id: str, proposal_id: str, confirm: bool) -> None:
    research_id = _validate_identifier(research_id, "research id")
    proposal_id = _validate_identifier(proposal_id, "proposal id")
    _require_confirm(confirm, "research proposal submission")
    _, client = _active_client(ctx.obj.data_dir)
    # Refresh the authoritative context before the state-changing submission.
    client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "research_get_context",
        "arguments": {},
        "source": CLI_SOURCE,
    })
    result = client.request_json("POST", "/api/tools/invoke", {
        "research_id": research_id,
        "tool": "experiment_submit",
        "arguments": {"proposal_id": proposal_id},
        "source": CLI_SOURCE,
    })
    _success(ctx, result, status="submitted")


@research.command("approve")
@click.argument("decision_id")
@click.option("--confirm", is_flag=True, help="Explicitly approve the pending human decision.")
@click.pass_context
def research_approve(ctx: click.Context, decision_id: str, confirm: bool) -> None:
    decision_id = _validate_identifier(decision_id, "decision id")
    _require_confirm(confirm, "research decision approval")
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("POST", f"/api/decision/{urllib.parse.quote(decision_id, safe='')}/approve"), status="approved")


@research.command("status")
@click.argument("research_id")
@click.pass_context
def research_status(ctx: click.Context, research_id: str) -> None:
    research_id = _validate_identifier(research_id, "research id")
    _, client = _active_client(ctx.obj.data_dir)
    _success(ctx, client.request_json("GET", f"/api/research/{urllib.parse.quote(research_id, safe='')}"))


def main(argv: list[str] | None = None) -> int:
    try:
        cli.main(args=argv, prog_name="topoptctl", standalone_mode=False)
    except TopoptCtlError as exc:
        click.echo(render_output(redact_for_output(_api_error_payload(exc)), json_output=True), err=False)
        return 2
    except click.ClickException as exc:
        click.echo(render_output({"ok": False, "error": {"code": "USAGE", "message": exc.format_message()}}, json_output=True), err=False)
        return 2
    except click.exceptions.Exit as exc:
        return int(exc.exit_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
