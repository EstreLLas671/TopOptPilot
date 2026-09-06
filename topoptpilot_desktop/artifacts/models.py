"""Validated contracts shared by engineering runs and research experiments."""

from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OwnerType(str, Enum):
    ENGINEERING_RUN = "engineering-run"
    RESEARCH_EXPERIMENT = "research-experiment"


class SolverLane(str, Enum):
    LOCAL_MATLAB = "local-matlab"
    COMPILED_RUNTIME = "compiled-runtime"
    PYTHON_FEM = "python-fem"
    MATLAB_MCP = "matlab-mcp"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorSource(str, Enum):
    TAURI = "tauri"
    ENGINEERING = "engineering"
    RESEARCH = "research"
    MATLAB = "matlab"
    RUNTIME = "runtime"


class ContractModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ArtifactRef(ContractModel):
    relative_path: str = Field(alias="relativePath", min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    media_type: str = Field(alias="mediaType", min_length=1, max_length=200)
    size_bytes: int = Field(alias="sizeBytes", ge=0)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("artifact paths must use forward slashes")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {".", ""}:
            raise ValueError("artifact paths must stay within the run directory")
        return value


class ErrorEnvelope(ContractModel):
    code: str = Field(min_length=1, max_length=120, pattern=r"^[A-Z0-9_]+$")
    source: ErrorSource
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool
    details: dict[str, Any] | None = None


class RunArtifact(ContractModel):
    run_id: str = Field(alias="runId", min_length=1, max_length=160)
    owner_type: OwnerType = Field(alias="ownerType")
    owner_id: str = Field(alias="ownerId", min_length=1, max_length=160)
    lane: SolverLane
    status: RunStatus
    config_digest: str = Field(alias="configDigest", pattern=r"^[0-9a-fA-F]{64}$")
    metrics: dict[str, float | None] = Field(default_factory=dict)
    snapshots: list[ArtifactRef] = Field(default_factory=list)
    files: list[ArtifactRef] = Field(default_factory=list)
    provenance: dict[str, str]
    error: ErrorEnvelope | None = None

    @model_validator(mode="after")
    def validate_status_evidence(self) -> "RunArtifact":
        if self.status is RunStatus.COMPLETED:
            is_solver = self.provenance.get("resultKind") == "solver"
            has_backend = bool(self.provenance.get("backend"))
            if not is_solver or not has_backend or not self.files:
                raise ValueError("completed artifacts require real solver provenance and output files")
        if self.status is RunStatus.FAILED and self.error is None:
            raise ValueError("failed artifacts require an error envelope")
        return self