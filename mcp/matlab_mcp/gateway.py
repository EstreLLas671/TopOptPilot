"""Executor-only security boundary in front of the official MATLAB MCP server."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .matlab_connector import MatlabConnector, MatlabMcpError


class MatlabGateway:
    """Expose one topology-optimization operation; never expose MCP built-ins."""

    def __init__(self, connector: MatlabConnector, research_root: str | Path):
        self.connector = connector
        self.research_root = Path(research_root).resolve()

    def run_topopt_task(self, task_path: str | Path, result_path: str | Path) -> dict[str, Any]:
        task = Path(task_path).resolve()
        result = Path(result_path).resolve()
        for path in (task, result):
            if self.research_root not in path.parents or path.suffix.lower() != ".json":
                raise MatlabMcpError("MatlabGateway denied a path outside the research root")
        if task.parent != result.parent:
            raise MatlabMcpError("MATLAB task and result must share one controlled job directory")
        try:
            payload = json.loads(task.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MatlabMcpError("MATLAB task JSON is invalid") from exc
        if payload.get("dimension") not in {2, 3} or not isinstance(payload.get("config"), dict):
            raise MatlabMcpError("MATLAB task schema is invalid")
        config = payload["config"]
        operation = str(payload.get("operation", "solve"))
        if operation not in {"solve", "capabilities", "preview_geometry"}:
            raise MatlabMcpError("MatlabGateway denied an unsupported operation")
        if not (.1 <= float(config.get("volfrac", -1)) <= .7
                and .75 <= float(config.get("rmin", -1)) <= 4
                and 1 <= float(config.get("penal", -1)) <= 5):
            raise MatlabMcpError("MATLAB task escaped the approved parameter envelope")
        return self.connector.call_topopt(task, result)

    def health(self) -> dict[str, Any]:
        value = self.connector.health()
        binary = Path(value.get("binary") or "")
        value["binary_sha256"] = (hashlib.sha256(binary.read_bytes()).hexdigest()
                                  if binary.is_file() else None)
        value["gateway"] = "MatlabGateway"
        value["allowed_operation"] = "run_topopt_task"
        return value
