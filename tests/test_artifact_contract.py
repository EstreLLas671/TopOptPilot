from __future__ import annotations

import pytest
from pydantic import ValidationError

from idesktop_v2.artifacts.models import (
    ArtifactRef,
    ErrorEnvelope,
    ErrorSource,
    OwnerType,
    RunArtifact,
    RunStatus,
    SolverLane,
)


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        relative_path="results/final.json",
        sha256="a" * 64,
        media_type="application/json",
        size_bytes=128,
    )


def test_run_artifact_serializes_the_shared_camel_case_contract() -> None:
    artifact = RunArtifact(
        run_id="run-001",
        owner_type=OwnerType.ENGINEERING_RUN,
        owner_id="engineering-001",
        lane=SolverLane.LOCAL_MATLAB,
        status=RunStatus.RUNNING,
        config_digest="b" * 64,
        metrics={"compliance": None},
        provenance={"backend": "matlab", "resultKind": "solver"},
    )

    payload = artifact.model_dump(mode="json", by_alias=True)

    assert payload["runId"] == "run-001"
    assert payload["ownerType"] == "engineering-run"
    assert payload["lane"] == "local-matlab"
    assert payload["configDigest"] == "b" * 64
    assert payload["snapshots"] == []
    assert payload["files"] == []


def test_completed_artifact_requires_real_solver_provenance_and_output() -> None:
    with pytest.raises(ValidationError, match="completed artifacts require real solver provenance"):
        RunArtifact(
            run_id="run-demo",
            owner_type=OwnerType.ENGINEERING_RUN,
            owner_id="engineering-demo",
            lane=SolverLane.LOCAL_MATLAB,
            status=RunStatus.COMPLETED,
            config_digest="c" * 64,
            provenance={"backend": "matlab", "resultKind": "demo"},
        )

    artifact = RunArtifact(
        run_id="run-real",
        owner_type=OwnerType.ENGINEERING_RUN,
        owner_id="engineering-real",
        lane=SolverLane.LOCAL_MATLAB,
        status=RunStatus.COMPLETED,
        config_digest="d" * 64,
        files=[_artifact_ref()],
        provenance={"backend": "matlab", "resultKind": "solver"},
    )

    assert artifact.status is RunStatus.COMPLETED


def test_failed_artifact_requires_a_typed_error_envelope() -> None:
    with pytest.raises(ValidationError, match="failed artifacts require an error envelope"):
        RunArtifact(
            run_id="run-failed",
            owner_type=OwnerType.RESEARCH_EXPERIMENT,
            owner_id="experiment-001",
            lane=SolverLane.MATLAB_MCP,
            status=RunStatus.FAILED,
            config_digest="e" * 64,
            provenance={"backend": "matlab-mcp", "resultKind": "solver"},
        )

    error = ErrorEnvelope(
        code="MATLAB_INFRASTRUCTURE",
        source=ErrorSource.MATLAB,
        message="MATLAB MCP exited before returning a result.",
        retryable=True,
    )
    artifact = RunArtifact(
        run_id="run-failed",
        owner_type=OwnerType.RESEARCH_EXPERIMENT,
        owner_id="experiment-001",
        lane=SolverLane.MATLAB_MCP,
        status=RunStatus.FAILED,
        config_digest="f" * 64,
        provenance={"backend": "matlab-mcp", "resultKind": "solver"},
        error=error,
    )

    assert artifact.error == error


def test_artifact_rejects_non_sha256_digests_and_parent_paths() -> None:
    with pytest.raises(ValidationError):
        ArtifactRef(
            relative_path="../secret.txt",
            sha256="a" * 64,
            media_type="text/plain",
            size_bytes=1,
        )

    with pytest.raises(ValidationError):
        RunArtifact(
            run_id="run-invalid",
            owner_type=OwnerType.ENGINEERING_RUN,
            owner_id="engineering-invalid",
            lane=SolverLane.COMPILED_RUNTIME,
            status=RunStatus.QUEUED,
            config_digest="not-a-digest",
            provenance={"backend": "runtime", "resultKind": "solver"},
        )