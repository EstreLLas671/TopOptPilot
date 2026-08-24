from __future__ import annotations

from pathlib import Path

from topoptpilot.service import ResearchService


def test_research_service_defaults_to_idesktop_v2_local_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("TOPPILOT_DATA_DIR", raising=False)
    monkeypatch.delenv("IDESKTOP_V2_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    service = ResearchService(max_workers=1)
    try:
        assert service.data_dir == (tmp_path / "iDeskTopV2").resolve()
    finally:
        service.close()