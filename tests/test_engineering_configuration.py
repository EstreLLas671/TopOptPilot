"""Regression tests for the shared persisted MATLAB preference."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from topoptpilot_desktop.engineering.configuration import configured_matlab_path


def _write_settings_database(data_dir: Path, matlab_root: Path) -> None:
    database = data_dir / "research.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE app_settings (id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO app_settings (id, settings_json) VALUES (?, ?)",
            (1, json.dumps({"compute": {"matlab_root": str(matlab_root)}})),
        )
        connection.commit()
    finally:
        connection.close()


def test_engineering_uses_persisted_matlab_root_with_one_shot_override(monkeypatch, tmp_path: Path) -> None:
    persisted = tmp_path / "MATLAB-persisted"
    override = tmp_path / "MATLAB-override"
    _write_settings_database(tmp_path, persisted)
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TOPPILOT_DATA_DIR", raising=False)
    monkeypatch.delenv("TOPOPTPILOT_MATLAB_PATH", raising=False)

    assert configured_matlab_path() == str(persisted)

    monkeypatch.setenv("TOPOPTPILOT_MATLAB_PATH", str(override))
    assert configured_matlab_path() == str(override)


def test_engineering_ignores_malformed_persisted_matlab_preference(monkeypatch, tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE app_settings (id INTEGER PRIMARY KEY, settings_json TEXT NOT NULL)"
        )
        connection.execute("INSERT INTO app_settings (id, settings_json) VALUES (?, ?)", (1, "{bad"))
        connection.commit()
    finally:
        connection.close()
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("TOPPILOT_DATA_DIR", raising=False)
    monkeypatch.delenv("TOPOPTPILOT_MATLAB_PATH", raising=False)

    assert configured_matlab_path() is None
