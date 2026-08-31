"""Authenticated identity endpoint for a ``topoptctl``-owned sidecar.

The endpoint is present only when a sidecar was explicitly started for the
headless CLI.  It lets the CLI prove that a persisted PID/port record points
to the daemon it created before stopping it; the actual bearer token remains
in Windows Credential Manager.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException


router = APIRouter(tags=["headless"])


@router.get("/api/headless/session")
def headless_session() -> dict[str, str]:
    session_id = os.environ.get("TOPPILOT_HEADLESS_SESSION_ID", "").strip()
    if not session_id:
        raise HTTPException(status_code=404, detail="headless CLI session is not active")
    return {"sessionId": session_id, "mode": "headless-loopback"}
