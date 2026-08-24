from __future__ import annotations

from pathlib import Path

from idesktop_v2.engineering.runs import _data_root, engineering_matlab_source_root


def test_engineering_matlab_source_root_prefers_staged_resource(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOPPILOT_RESOURCE_ROOT", str(tmp_path))
    assert engineering_matlab_source_root() == tmp_path / "matlab" / "engineering"


def test_engineering_runs_follow_shared_topoptpilot_data_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("IDESKTOP_V2_DATA_DIR", raising=False)
    monkeypatch.setenv("TOPPILOT_DATA_DIR", str(tmp_path))
    assert _data_root() == tmp_path.resolve() / "runs"
