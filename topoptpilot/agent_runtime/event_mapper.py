"""Map Pi wire events onto the stable Workspace event vocabulary."""

from __future__ import annotations

from typing import Any


def assistant_text(message: dict[str, Any] | None) -> str:
    if not message:
        return ""
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    return "".join(item.get("text", "") for item in content
                   if isinstance(item, dict) and item.get("type") == "text")


def map_pi_event(event: dict[str, Any]) -> dict[str, Any] | None:
    kind = event.get("type")
    if kind == "message_end":
        message = event.get("message") or event.get("assistantMessage")
        text = assistant_text(message)
        role = (message or {}).get("role")
        if role == "assistant" and text:
            return {"kind": "AGENT_MESSAGE", "title": "PI RESEARCH AGENT", "body": text}
        if role == "assistant" and (message or {}).get("stopReason") == "error":
            return {"kind": "SYSTEM", "title": "PI MODEL ERROR",
                    "body": (message or {}).get("errorMessage", "Model request failed.")}
    if kind in {"tool_execution_start", "tool_call_start"}:
        return {"kind": "TOOL_CALL", "title": event.get("toolName", "PI TOOL"),
                "body": "Pi requested an allowlisted scientific tool.", "payload": event}
    if kind in {"tool_execution_end", "tool_call_end"}:
        return {"kind": "TOOL_RESULT", "title": event.get("toolName", "PI TOOL"),
                "body": "Scientific tool returned to Pi.", "payload": event}
    if kind == "agent_end":
        return {"kind": "SYSTEM", "title": "PI TURN COMPLETE", "body": "Pi is idle."}
    if kind in {"auto_compaction_start", "auto_compaction_end", "retry_start", "retry_end"}:
        return {"kind": "SYSTEM", "title": kind.upper().replace("_", " "), "body": "Pi runtime event."}
    return None
