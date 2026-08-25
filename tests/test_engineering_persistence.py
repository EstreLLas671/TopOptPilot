from __future__ import annotations

import hashlib

import pytest

from idesktop_v2.artifacts.models import ArtifactRef, RunStatus, SolverLane
from idesktop_v2.engineering import comparison_schemes as comparison_module
from idesktop_v2.engineering.comparison_schemes import ComparisonSchemeStore
from idesktop_v2.engineering.runs import RunManager, _Run, _data_root


def _record(tmp_path, monkeypatch, suffix: str = "a", status: RunStatus = RunStatus.COMPLETED):
    monkeypatch.setenv("IDESKTOP_V2_DATA_DIR", str(tmp_path))
    run_id = "eng-" + suffix * 32
    run_dir = _data_root() / run_id
    run_dir.mkdir(parents=True)
    artifact = run_dir / "result.json"
    artifact.write_text('{"status":"completed"}', encoding="utf-8")
    reference = ArtifactRef(
        relativePath="result.json",
        sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        mediaType="application/json",
        sizeBytes=artifact.stat().st_size,
    )
    return _Run(
        run_id=run_id,
        owner_id="engineering",
        lane=SolverLane.PYTHON_FEM,
        task={"dimension": "2d", "geometry": {"nelx": 8, "nely": 4}},
        config_digest="c" * 64,
        run_dir=run_dir,
        status=status,
        files=[reference],
        provenance={
            "resultKind": "solver",
            "backend": "python-fem",
            "lane": "python-fem",
        },
        events=[{"type": "status", "status": status.value}],
    )


def test_run_manifest_restores_completed_run_and_events(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, monkeypatch)
    first = RunManager()
    first.persist(record)

    restored = RunManager().get(record.run_id)

    assert restored is not None
    assert restored.status is RunStatus.COMPLETED
    assert restored.task["dimension"] == "2d"
    assert restored.events == record.events
    assert restored.files[0].sha256 == record.files[0].sha256


def test_run_manifest_marks_stale_active_run_as_interrupted(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, monkeypatch, suffix="b", status=RunStatus.RUNNING)
    RunManager().persist(record)

    restored = RunManager().get(record.run_id)

    assert restored is not None
    assert restored.status is RunStatus.FAILED
    assert restored.error is not None
    assert restored.error.code == "RUN_INTERRUPTED"


def test_comparison_scheme_persists_and_keeps_real_artifacts(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, monkeypatch, suffix="d")
    run_manager = RunManager()
    run_manager.persist(record)
    monkeypatch.setattr(comparison_module, "manager", run_manager)
    store = ComparisonSchemeStore()

    created = store.create(record.run_id, "二维基准")
    restored = ComparisonSchemeStore().get(created["id"])

    assert restored is not None
    assert restored["runId"] == record.run_id
    assert restored["integrity"] == "verified"
    assert store.delete(created["id"]) is True
    assert (record.run_dir / "result.json").is_file()
    assert ComparisonSchemeStore().get(created["id"]) is None


def test_comparison_scheme_rejects_tampered_artifact(monkeypatch, tmp_path) -> None:
    record = _record(tmp_path, monkeypatch, suffix="e")
    run_manager = RunManager()
    run_manager.persist(record)
    monkeypatch.setattr(comparison_module, "manager", run_manager)
    (record.run_dir / "result.json").write_text("tampered", encoding="utf-8")

    with pytest.raises(ValueError, match="完整性校验失败"):
        ComparisonSchemeStore().create(record.run_id, "损坏方案")
