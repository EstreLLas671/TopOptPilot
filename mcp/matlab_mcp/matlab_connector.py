"""Persistent, minimal MCP stdio client for the official MathWorks server."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any


class MatlabMcpError(RuntimeError):
    pass


class MatlabConnector:
    PROTOCOL_VERSION = "2025-06-18"

    def __init__(self, project_root: str | Path | None = None,
                 job_root: str | Path | None = None, timeout: float = 600):
        self.root = Path(project_root or os.getenv(
            "TOPPILOT_RESOURCE_ROOT", Path(__file__).parents[2])).resolve()
        packaged_adapter = self.root / "mcp/matlab_mcp"
        self.adapter_dir = (packaged_adapter if packaged_adapter.exists()
                            else Path(__file__).resolve().parent)
        self.binary = Path(os.getenv("TOPPILOT_MATLAB_MCP", self.root /
                           "vendor/matlab-mcp-server/matlab-mcp-server-windows-x64.exe"))
        self.matlab_root = self._find_matlab_root()
        self.job_root = Path(job_root).resolve() if job_root else None
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.pending: dict[str, queue.Queue] = {}
        self.stderr: list[str] = []
        self.tools: set[str] = set()
        self._write_lock = threading.Lock()
        self._start_lock = threading.RLock()

    @staticmethod
    def _find_matlab_root() -> Path | None:
        configured = os.getenv("TOPPILOT_MATLAB_ROOT") or os.getenv("MATLAB_ROOT")
        if configured:
            return Path(configured).resolve()
        executable = shutil.which("matlab")
        if executable:
            return Path(executable).resolve().parent.parent
        if os.name == "nt":
            try:
                import winreg
                for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                        try:
                            key = winreg.OpenKey(hive, r"SOFTWARE\MathWorks\MATLAB\9.16",
                                                 0, winreg.KEY_READ | view)
                            value, _ = winreg.QueryValueEx(key, "MATLABROOT")
                            candidate = Path(value).resolve()
                            if candidate.exists():
                                return candidate
                        except OSError:
                            continue
            except (ImportError, OSError):
                pass
            for candidate in (Path(r"D:\Apps\MATLAB R2024a"),
                              Path(r"C:\Program Files\MATLAB\R2024a")):
                if candidate.exists():
                    return candidate.resolve()
        return None

    def start(self) -> "MatlabConnector":
        with self._start_lock:
            if self.process and self.process.poll() is None:
                return self
            if not self.binary.exists():
                raise MatlabMcpError(f"MATLAB MCP binary not found: {self.binary}")
            if not self.matlab_root:
                raise MatlabMcpError("MATLAB installation was not found on PATH")
            args = [str(self.binary), f"--matlab-root={self.matlab_root}",
                    f"--initial-working-folder={self.adapter_dir}",
                    "--matlab-display-mode=nodesktop", "--matlab-session-mode=auto",
                    "--disable-telemetry=true",
                    f"--extension-file={self.adapter_dir / 'topopt-tools.json'}"]
            env = os.environ.copy()
            if self.job_root:
                env["TOPPILOT_MATLAB_JOB_ROOT"] = str(self.job_root)
            if "WINDIR" not in env and os.getenv("SystemRoot"):
                env["WINDIR"] = os.environ["SystemRoot"]
            self.process = subprocess.Popen(
                args, cwd=self.adapter_dir, env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            threading.Thread(target=self._stdout_loop, daemon=True).start()
            threading.Thread(target=self._stderr_loop, daemon=True).start()
            self.request("initialize", {
                "protocolVersion": self.PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "TopOptPilot", "version": "6.0.0"},
            }, timeout=30)
            self.notify("notifications/initialized", {})
            listing = self.request("tools/list", {}, timeout=30)
            self.tools = {item["name"] for item in listing.get("tools", [])}
            if "topopt_run_task" not in self.tools:
                raise MatlabMcpError("Restricted topopt_run_task tool was not registered")
            return self

    def request(self, method: str, params: dict[str, Any], timeout: float | None = None) -> dict:
        if not self.process or self.process.poll() is not None:
            raise MatlabMcpError("MATLAB MCP process is not running")
        request_id = uuid.uuid4().hex
        waiter: queue.Queue = queue.Queue(maxsize=1)
        self.pending[request_id] = waiter
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            response = waiter.get(timeout=timeout or self.timeout)
        except queue.Empty as exc:
            raise MatlabMcpError(f"MATLAB MCP timeout during {method}") from exc
        finally:
            self.pending.pop(request_id, None)
        if response.get("error"):
            error = response["error"]
            raise MatlabMcpError(str(error.get("message") or error))
        return response.get("result") or {}

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def call_topopt(self, task_path: Path, result_path: Path) -> dict:
        task_path, result_path = task_path.resolve(), result_path.resolve()
        if (not self.job_root or self.job_root not in task_path.parents
                or self.job_root not in result_path.parents
                or task_path.parent != result_path.parent):
            raise MatlabMcpError("MATLAB task/result paths must share a job directory under the research data root")
        self.start()
        response = self.request("tools/call", {"name": "topopt_run_task", "arguments": {
            "task_json_path": str(task_path), "result_json_path": str(result_path)}})
        if response.get("isError"):
            message = " ".join(str(item.get("text", "")) for item in response.get("content", []))
            raise MatlabMcpError(message or "MATLAB custom tool failed")
        if not result_path.exists():
            message = " ".join(str(item.get("text", "")) for item in response.get("content", []))
            raise MatlabMcpError("MATLAB MCP completed without a result file" +
                                 (f": {message}" if message else ""))
        return json.loads(result_path.read_text(encoding="utf-8"))

    def health(self) -> dict[str, Any]:
        running = bool(self.process and self.process.poll() is None)
        available = self.binary.exists() and self.matlab_root is not None
        return {"state": "READY" if running else ("AVAILABLE" if available else "UNAVAILABLE"),
                "server_version": "0.12.0", "matlab_root": str(self.matlab_root) if self.matlab_root else None,
                "binary": str(self.binary), "process_running": running,
                "restricted_tool": "topopt_run_task", "last_error": self.stderr[-1] if self.stderr else None}

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.tools.clear()

    def restart(self) -> dict[str, Any]:
        self.stop()
        self.start()
        return self.health()

    def configure(self, *, matlab_root: str | Path | None = None,
                  timeout: float | None = None) -> dict[str, Any]:
        """Apply controlled runtime settings; callers cannot alter MCP tool access."""
        with self._start_lock:
            if matlab_root is not None:
                candidate = Path(matlab_root).resolve()
                executable = candidate / "bin" / ("matlab.exe" if os.name == "nt" else "matlab")
                if not candidate.is_dir() or not executable.exists():
                    raise MatlabMcpError("MATLAB root must contain bin/matlab")
                self.matlab_root = candidate
            if timeout is not None:
                self.timeout = float(timeout)
            self.stop()
        return self.restart()

    def _write(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise MatlabMcpError("MATLAB MCP stdin is unavailable")
        with self._write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _stdout_loop(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                self.stderr.append(f"non-json stdout: {line.strip()[:300]}")
                continue
            waiter = self.pending.get(str(value.get("id", "")))
            if waiter:
                waiter.put(value)
        for waiter in list(self.pending.values()):
            waiter.put({"error": {"message": "MATLAB MCP process exited"}})

    def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())
            self.stderr[:] = self.stderr[-200:]
