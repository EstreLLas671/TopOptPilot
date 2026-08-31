"""Read the persisted, non-secret MATLAB preference for engineering jobs.

The desktop Settings page persists ``compute.matlab_root`` through
``ResearchService``.  Engineering runs must honor the same preference instead
of silently rediscovering a different MATLAB installation.  This module uses a
short-lived read-only SQLite connection to avoid importing the API singleton
or mutating research state from an engineering worker.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def _data_dir() -> Path:
    configured = os.environ.get("TOPOPTPILOT_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "TopOptPilot").resolve()


def configured_matlab_path() -> str | None:
    """Return an explicit engineering override or the persisted MATLAB root.

    The environment value remains the highest-priority, one-shot override for
    test and deployment scenarios.  The database is treated as untrusted input
    until its JSON shape and path type are checked; actual executable existence
    is still verified by the discovery/probe layer.
    """
    override = os.environ.get("TOPOPTPILOT_MATLAB_PATH")
    if override and override.strip():
        return override.strip()

    database = _data_dir() / "research.db"
    if not database.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True, timeout=1)
        try:
            row = connection.execute("SELECT settings_json FROM app_settings WHERE id=1").fetchone()
        finally:
            connection.close()
        if not row or not isinstance(row[0], str):
            return None
        payload = json.loads(row[0])
        candidate = (payload.get("compute") or {}).get("matlab_root")
        if not isinstance(candidate, str) or not candidate.strip() or len(candidate) > 500:
            return None
        return candidate.strip()
    except (OSError, sqlite3.Error, TypeError, ValueError, json.JSONDecodeError):
        return None
