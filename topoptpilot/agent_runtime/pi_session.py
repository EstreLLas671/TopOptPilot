"""Research-to-Pi-session registry backed by authoritative SQLite state."""

from __future__ import annotations

import uuid


class PiSessionRegistry:
    def __init__(self, store):
        self.store = store

    def session_id(self, research_id: str) -> str:
        current = self.store.get_agent_session(research_id) or {}
        return current.get("session_id") or str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"topoptpilot:{research_id}"))

    def record(self, research_id: str, state: dict, status: str = "IDLE") -> dict:
        return self.store.upsert_agent_session(
            research_id, session_id=state["sessionId"], session_file=state.get("sessionFile"),
            status=status, context_usage=state.get("contextUsage", 0.0))

    def mark(self, research_id: str, status: str, **fields) -> dict:
        return self.store.upsert_agent_session(research_id, status=status, **fields)
