"""One persistent official Pi JSON-RPC process per research project."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .event_mapper import map_pi_event
from .tool_gateway import ToolGateway
from .reviewer import ReviewerWorkflow
from .pi_session import PiSessionRegistry


TOOLS = (
    "research_get_context,research_query_history,research_get_budget,policy_compile_intent,"
    "experiment_preview,experiment_submit,experiment_status,experiment_result,"
    "experiment_compare,research_get_pareto,failure_get_evidence"
)


class PiProcess:
    def __init__(self, bridge: "PiBridge", research_id: str):
        self.bridge, self.research_id = bridge, research_id
        self.process: subprocess.Popen | None = None
        self.pending: dict[str, queue.Queue] = {}
        self.events: queue.Queue = queue.Queue()
        self.stderr: list[str] = []
        self.fallback_on_error = False
        self.last_prompt = ""
        self.retry_count = 0
        self._stream_buffer = ""
        self._write_lock = threading.Lock()

    def start(self):
        if self.process and self.process.poll() is None:
            return self
        env = os.environ.copy()
        env.update({
            "PI_CODING_AGENT_DIR": str(self.bridge.config_dir),
            "TOPPILOT_TOOL_URL": self.bridge.gateway.url,
            "TOPPILOT_RESEARCH_ID": self.research_id,
            "TOPPILOT_TOOL_TOKEN": self.bridge.gateway.token,
        })
        session_id = self.bridge.sessions.session_id(self.research_id)
        args = [str(self.bridge.node), str(self.bridge.cli), "--mode", "rpc",
                "--provider", "dashscope", "--model", self.bridge.model,
                "--session-id", session_id,
                "--session-dir", str(self.bridge.session_dir),
                "--no-extensions", "--extension", str(self.bridge.root / ".pi/extensions/topopt-tools.ts"),
                "--no-skills", "--no-prompt-templates",
                "--no-builtin-tools", "--tools", TOOLS, "--approve"]
        self.process = subprocess.Popen(
            args, cwd=self.bridge.root, env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(target=self._stdout_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()
        state = self.request("get_state", timeout=20)["data"]
        self.bridge.sessions.record(self.research_id, state)
        return self

    def request(self, command: str, timeout: float = 30, **data) -> dict:
        if not self.process or self.process.poll() is not None:
            raise RuntimeError("Pi RPC process is not running")
        request_id = uuid.uuid4().hex
        waiter: queue.Queue = queue.Queue(maxsize=1)
        self.pending[request_id] = waiter
        payload = {"id": request_id, "type": command, **data}
        with self._write_lock:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        try:
            response = waiter.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError(f"Pi RPC {command} timed out") from exc
        finally:
            self.pending.pop(request_id, None)
        if not response.get("success"):
            raise RuntimeError(response.get("error", f"Pi RPC {command} failed"))
        return response

    def prompt(self, message: str, fallback_on_error: bool = False) -> None:
        self.fallback_on_error = fallback_on_error
        self.last_prompt = message
        self._stream_buffer = ""
        self.bridge.sessions.mark(self.research_id, "STREAMING", stream_text="", last_error=None)
        self.request("prompt", message=message)

    def abort(self):
        return self.request("abort")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.bridge.sessions.mark(self.research_id, "OFFLINE")

    def _stdout_loop(self):
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                self.stderr.append(f"non-json stdout: {line[:300]}")
                continue
            if value.get("type") == "response" and value.get("id") in self.pending:
                self.pending[value["id"]].put(value)
                continue
            self.events.put(value)
            if value.get("type") == "message_update":
                update = value.get("assistantMessageEvent") or {}
                if update.get("type") in {"text_delta", "text"}:
                    self._stream_buffer += str(update.get("delta") or update.get("text") or "")
                    usage = value.get("usage") or {}
                    tokens = float(usage.get("totalTokens") or usage.get("total") or 0)
                    self.bridge.sessions.mark(self.research_id, "STREAMING",
                                              stream_text=self._stream_buffer,
                                              context_usage=min(1.0, tokens / 1_000_000))
            mapped = map_pi_event(value)
            if mapped:
                self.bridge.service.store.append_event(
                    self.research_id, mapped["kind"], mapped["title"], mapped["body"],
                    payload=mapped.get("payload"))
            if value.get("type") == "agent_end":
                messages = value.get("messages") or []
                failed = any(item.get("role") == "assistant" and item.get("stopReason") == "error"
                             for item in messages if isinstance(item, dict))
                error = next((item.get("errorMessage") for item in reversed(messages)
                              if isinstance(item, dict) and item.get("errorMessage")), None)
                self.bridge.sessions.mark(self.research_id, "IDLE", stream_text="",
                                          last_error=error)
                research = self.bridge.service.store.get_research(self.research_id)
                retryable = failed and error and "401" not in error and "invalid_api_key" not in error
                if retryable and self.retry_count < 2:
                    self.retry_count += 1
                    threading.Thread(target=self.prompt,
                                     args=(self.last_prompt, self.fallback_on_error), daemon=True).start()
                else:
                    if failed and self.fallback_on_error and research and research.get("mode") == "AUTONOMOUS":
                        threading.Thread(target=self.bridge.service._safe_mode_next,
                                         args=(self.research_id,), daemon=True).start()
                    self.fallback_on_error = False
                    self.retry_count = 0
            for callback in self.bridge.listeners:
                callback(self.research_id, value)

    def _stderr_loop(self):
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            self.stderr.append(line.rstrip())
            if len(self.stderr) > 100:
                self.stderr.pop(0)


class PiBridge:
    def __init__(self, service, root: str | Path | None = None):
        self.service = service
        self.root = Path(root or Path(__file__).parents[2]).resolve()
        self.node = Path(os.environ.get("TOPPILOT_NODE", shutil_which("node") or "node"))
        self.cli = self.root / "node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
        self.model = os.environ.get("QWEN_MODEL", "qwen3.7-plus")
        self.config_dir = service.data_dir / "pi" / "config"
        self.session_dir = service.data_dir / "pi" / "sessions"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.processes: dict[str, PiProcess] = {}
        self.listeners: list[Callable[[str, dict], None]] = []
        self.sessions = PiSessionRegistry(service.store)
        self.gateway = ToolGateway(service).start()
        self.reviewer = ReviewerWorkflow(self)
        self._write_config()

    def _write_config(self):
        example = json.loads((self.root / ".pi/models.example.json").read_text(encoding="utf-8"))
        (self.config_dir / "models.json").write_text(json.dumps(example, indent=2), encoding="utf-8")
        settings = {"autoCompaction": True, "extensions": [str(self.root / ".pi/extensions/topopt-tools.ts")]}
        (self.config_dir / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def start(self, research_id: str) -> PiProcess:
        process = self.processes.get(research_id) or PiProcess(self, research_id)
        self.processes[research_id] = process
        return process.start()

    def send(self, research_id: str, message: str, skill: str | None = None,
             fallback_on_error: bool = False) -> None:
        if skill:
            skill_file = self.root / ".pi/skills" / skill / "SKILL.md"
            message = f"<active_skill>\n{skill_file.read_text(encoding='utf-8')}\n</active_skill>\n\n{message}"
        self.start(research_id).prompt(message, fallback_on_error=fallback_on_error)

    def cancel(self, research_id: str):
        return self.start(research_id).abort()

    def resume(self, research_id: str) -> PiProcess:
        return self.start(research_id)

    def health(self) -> dict[str, Any]:
        return {"available": self.cli.exists(), "status": "ready",
                "model": self.model, "sessions": len(self.processes)}

    def close(self):
        for process in list(self.processes.values()):
            process.stop()
        self.gateway.close()


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)
