from __future__ import annotations

from pathlib import Path

import pytest

from fastapi.testclient import TestClient
from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.research_artifacts import build_research_artifact_index


def test_research_artifact_index_returns_relative_verified_files(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "R-1" / "artifacts" / "E01"
    artifact_dir.mkdir(parents=True)
    density = artifact_dir / "density.npy"
    density.write_bytes(b"density")
    research = {"id": "R-1", "experiments": [{"id": "E01", "status": "SUCCESS", "backend": "python", "fidelity": "F0", "result": {"artifacts": {"density_path": str(density)}}}]}
    index = build_research_artifact_index(research, tmp_path)
    assert index["researchId"] == "R-1"
    assert index["experiments"][0]["files"][0]["relativePath"] == "R-1/artifacts/E01/density.npy"
    assert len(index["experiments"][0]["files"][0]["sha256"]) == 64


def test_research_artifact_index_rejects_paths_outside_research_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    research = {"id": "R-1", "experiments": [{"id": "E01", "status": "SUCCESS", "result": {"artifacts": {"log": str(outside)}}}]}
    with pytest.raises(ValueError, match="outside research data root"):
        build_research_artifact_index(research, tmp_path)


def test_research_artifact_endpoint_is_mounted_and_returns_404_for_unknown_research() -> None:
    response = TestClient(app).get("/api/research/unknown-v2/artifacts")
    assert response.status_code == 404