"""Packaging contracts for Windows desktop startup behavior."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_desktop_entrypoint_uses_the_gui_subsystem() -> None:
    source = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    assert '#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]' in source
