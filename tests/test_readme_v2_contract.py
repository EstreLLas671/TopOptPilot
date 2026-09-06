from __future__ import annotations

from pathlib import Path


def test_readme_describes_v2_credential_and_fidelity_boundaries() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "Windows Credential Manager" not in readme
    assert "F0–F3 全部通过 MATLAB MCP" not in readme
    assert "DASHSCOPE_API_KEY" in readme
    assert "F0/F1=Python 2D" in readme
    assert "F2=Python 3D" in readme
    assert "F3=MATLAB MCP" in readme
