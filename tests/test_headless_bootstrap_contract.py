"""Safety and invocation contract for the no-GUI dependency bootstrapper."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_headless.ps1"


def _powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell is required for the Windows headless bootstrap contract")
    return executable


def _run_bootstrap(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            *arguments,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )


def test_bootstrap_source_never_handles_secrets_or_starts_an_agent() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "DASHSCOPE_API_KEY" not in source
    assert "Credential Manager" not in source
    assert "Start-Process" not in source
    assert "Invoke-Expression" not in source
    assert "Remove-Item" not in source
    assert "--ignore-scripts" in source
    assert "ReinstallPiRuntime" in source


def test_bootstrap_skip_mode_is_machine_readable_and_side_effect_limited() -> None:
    completed = _run_bootstrap(
        "-VenvPath",
        ".venv",
        "-SkipPythonDependencies",
        "-SkipPiRuntime",
        "-Json",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["status"] == "ready"
    assert payload["pythonDependencies"] == "skipped"
    assert payload["piRuntime"] == "skipped"
    assert "no credentials were read or written" in payload["guarantees"]


def test_bootstrap_rejects_venv_paths_outside_the_repository(tmp_path: Path) -> None:
    completed = _run_bootstrap(
        "-VenvPath",
        str(tmp_path / "outside-venv"),
        "-SkipPythonDependencies",
        "-SkipPiRuntime",
        "-Json",
    )
    assert completed.returncode == 2
    payload = json.loads(completed.stdout)
    assert payload["ok"] is False
    assert payload["status"] == "failed"
    assert "subdirectory of this repository" in payload["error"]
