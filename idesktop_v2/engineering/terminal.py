"""Safe file-bridge controller for an explicitly started MATLAB terminal."""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

MAX_COMMAND_BYTES = 64 * 1024


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def default_bridge_script() -> Path | None:
    """Locate the authoritative engineering bridge in source or staged resources."""
    resource_root = os.environ.get("TOPPILOT_RESOURCE_ROOT")
    candidates = []
    if resource_root:
        candidates.append(Path(resource_root) / "matlab" / "engineering" / "idesktop_terminal_bridge.m")
    candidates.append(Path(__file__).resolve().parents[2] / "matlab" / "engineering" / "idesktop_terminal_bridge.m")
    return next((path for path in candidates if path.is_file()), None)


class TerminalManager:
    def __init__(self, data_root: Path | None = None) -> None:
        configured = os.environ.get("IDESKTOP_V2_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
        local = Path(configured).expanduser().resolve() if configured else Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "iDeskTopV2"
        self.root = Path(data_root or local) / "sessions"
        self.sessions: dict[str, dict[str, Any]] = {}

    def start(
        self,
        *,
        project_root: Path | str,
        executable: str | None = None,
        bridge_script: Path | str | None = None,
    ) -> dict[str, Any]:
        project = Path(project_root).resolve()
        if not project.is_dir():
            raise ValueError("项目目录不存在")
        if executable and not Path(executable).is_file():
            raise ValueError("MATLAB 可执行文件不存在")
        session_id = f"matlab-{uuid.uuid4().hex}"
        session_root = self.root / session_id
        commands = session_root / "commands"
        results = session_root / "results"
        commands.mkdir(parents=True, exist_ok=False)
        results.mkdir()
        config = session_root / "config.json"
        _atomic_json(config, {"project_root": str(project), "session_root": str(session_root)})

        script = Path(bridge_script) if bridge_script else default_bridge_script()
        if executable and script is None:
            raise ValueError("MATLAB 命令桥不存在")
        if script is not None:
            if not script.is_file():
                raise ValueError("MATLAB 命令桥不存在")
            (session_root / "idesktop_terminal_bridge.m").write_bytes(script.read_bytes())

        child = None
        status = "waiting-matlab"
        if executable:
            root = str(session_root).replace("\\", "/").replace("'", "''")
            child = subprocess.Popen(
                [executable, "-wait", "-batch", f"addpath('{root}'); idesktop_terminal_bridge('{root}/config.json');"],
                cwd=session_root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            status = "starting"
        record = {
            "sessionId": session_id,
            "root": session_root,
            "commands": commands,
            "results": results,
            "nextId": 1,
            "status": status,
            "child": child,
            "projectRoot": str(project),
        }
        self.sessions[session_id] = record
        return {"sessionId": session_id, "status": status, "projectRoot": str(project)}

    def _get(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions[session_id]

    def command(self, session_id: str, raw_command: str) -> dict[str, Any]:
        session = self._get(session_id)
        if session["status"] not in {"starting", "ready", "busy", "waiting-matlab"}:
            raise ValueError("MATLAB 会话尚未就绪")
        command = str(raw_command).strip()
        if not command:
            raise ValueError("MATLAB 命令不能为空")
        if len(command.encode("utf-8")) > MAX_COMMAND_BYTES:
            raise ValueError("MATLAB 命令过长")
        command_id = int(session["nextId"])
        session["nextId"] = command_id + 1
        target = session["commands"] / f"command_{command_id:08d}.json"
        _atomic_json(target, {"id": command_id, "command": command})
        session["status"] = "busy" if session["status"] != "waiting-matlab" else session["status"]
        return {"queued": True, "id": command_id, "command": command}

    def poll(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        results: list[dict[str, Any]] = []
        for path in sorted(session["results"].glob("result_*.json")):
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        ready = session["root"] / "ready"
        failure = session["root"] / "failure.txt"
        if failure.exists():
            session["status"] = "failed"
        elif ready.exists() and session["status"] == "starting":
            session["status"] = "ready"
        return {"sessionId": session_id, "status": session["status"], "results": results}

    def stop(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        (session["root"] / "stop").write_text("stop", encoding="utf-8")
        child = session.get("child")
        if child and child.poll() is None:
            child.terminate()
        session["status"] = "stopped"
        return {"sessionId": session_id, "status": "stopped"}


manager = TerminalManager()
