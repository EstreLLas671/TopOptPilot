from __future__ import annotations

from pathlib import Path

from topoptpilot_desktop.engineering.artifact_index import discover_artifact_files, media_type_for


def test_artifact_index_recurses_and_separates_snapshots(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text("{}", encoding="utf-8")
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    (snapshots / "manifest.json").write_text("{}", encoding="utf-8")
    (snapshots / "iter_0001_density.bin").write_bytes(b"1234")
    files, frames = discover_artifact_files(tmp_path)
    assert [path.relative_to(tmp_path).as_posix() for path in files] == ["result.json"]
    assert [path.relative_to(tmp_path).as_posix() for path in frames] == [
        "snapshots/iter_0001_density.bin",
        "snapshots/manifest.json",
    ]


def test_artifact_index_assigns_stable_media_types() -> None:
    assert media_type_for(Path("result.json")) == "application/json"
    assert media_type_for(Path("density.csv")) == "text/csv"
    assert media_type_for(Path("final_density.bin")) == "application/vnd.topoptpilot.float32"
