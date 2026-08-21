"""Public data contracts shared by Streamlit, API and the research core."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ExperimentStatus(str, Enum):
    WAITING = "WAITING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DecisionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EventKind(str, Enum):
    USER = "USER"
    PLANNER = "PLANNER"
    SAFETY = "SAFETY POLICY"
    EXPERIMENT = "EXPERIMENT"
    ANALYSIS = "ANALYSIS"
    FEEDBACK = "NEXT DECISION"
    HUMAN = "HUMAN OVERRIDE"
    SYSTEM = "SYSTEM"
    AGENT = "AGENT_MESSAGE"
    TOOL_CALL = "TOOL_CALL"
    TOOL_RESULT = "TOOL_RESULT"
    EVIDENCE = "EVIDENCE"


class Fidelity(str, Enum):
    F0 = "F0"
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"


class IntentType(str, Enum):
    ESTABLISH_BASELINE = "ESTABLISH_BASELINE"
    EXPLORE_PARAMETER = "EXPLORE_PARAMETER"
    REDUCE_GRAYNESS = "REDUCE_GRAYNESS"
    RESTORE_CONNECTIVITY = "RESTORE_CONNECTIVITY"
    TEST_COMPETING_EXPLANATIONS = "TEST_COMPETING_EXPLANATIONS"
    UPGRADE_FIDELITY = "UPGRADE_FIDELITY"
    VERIFY_CANDIDATE = "VERIFY_CANDIDATE"


class FailureType(str, Enum):
    HIGH_GRAY = "HIGH_GRAY"
    DISCONNECTION = "DISCONNECTION"
    DIVERGENCE = "DIVERGENCE"
    OSCILLATION = "OSCILLATION"
    VOLUME_VIOLATION = "VOLUME_VIOLATION"
    POOR_COMPLIANCE = "POOR_COMPLIANCE"
    INFRASTRUCTURE = "INFRASTRUCTURE"


class SafetyStatus(str, Enum):
    PASS = "PASS"
    REJECTED = "REJECTED"
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"


class TerminationReason(str, Enum):
    GOAL_ACHIEVED = "GOAL_ACHIEVED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PLATEAU = "PLATEAU"
    USER_STOPPED = "USER_STOPPED"


class BudgetSpec(BaseModel):
    total: int = Field(default=12, ge=1)
    f0: int = Field(default=6, ge=0)
    f1: int = Field(default=4, ge=0)
    f2: int = Field(default=2, ge=0)
    f3: int = Field(default=1, ge=0)
    time_seconds: float | None = Field(default=None, gt=0)


class ResearchCreate(BaseModel):
    name: str = Field(default="MBB Beam", min_length=1, max_length=120)
    goal: str = "Minimize compliance while satisfying constraints."
    constraints: dict[str, Any] = Field(default_factory=lambda: {
        "volume_fraction": 0.40,
        "gray_max": 0.05,
        "connected": True,
    })
    budget_total: int = Field(default=12, ge=1, le=10000)
    budgets: BudgetSpec | None = None
    mode: str = "COPILOT"
    geometry: dict[str, Any] = Field(default_factory=lambda: {"type": "MBB", "dimensions": [3.0, 1.0]})
    material: dict[str, Any] = Field(default_factory=lambda: {"E": 1.0, "nu": 0.3})
    loads: list[dict[str, Any]] = Field(default_factory=lambda: [{"type": "vertical", "magnitude": 1.0}])
    boundary_conditions: dict[str, Any] = Field(default_factory=lambda: {"type": "MBB"})
    hypothesis: str | None = None
    locale: str = "zh-CN"

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        if value not in {"zh-CN", "en-US"}:
            raise ValueError("locale must be zh-CN or en-US")
        return value

    def normalized_budgets(self) -> dict[str, Any]:
        value = self.budgets or BudgetSpec(total=self.budget_total)
        data = value.model_dump()
        data["total"] = self.budget_total
        return data


class ExperimentCreate(BaseModel):
    purpose: str = "Establish a topology optimization baseline."
    fidelity: str = "F0 — 2D Coarse"
    mesh_level: str = "coarse"
    backend: str = "python"
    parameters: dict[str, Any] = Field(default_factory=lambda: {
        "volfrac": 0.40,
        "rmin": 1.5,
        "penal": 3.0,
        "beta": 1.0,
        "max_iter": 80,
    })
    warm_start: str | None = None
    requires_approval: bool = False
    proposal_id: str | None = None
    intent: str = "MANUAL"

    @field_validator("backend")
    @classmethod
    def validate_backend(cls, value: str) -> str:
        if value not in {"python", "python3d", "matlab", "simulate"}:
            raise ValueError("backend must be python, python3d, matlab, or simulate")
        return value


class WorkspaceCommandResult(BaseModel):
    ok: bool
    message: str
    action: str = "message"
    data: dict[str, Any] = Field(default_factory=dict)


class IntentRequest(BaseModel):
    intent: IntentType
    preserve: list[str] = Field(default_factory=list)
    factor: str | None = None
    explanations: list[str] = Field(default_factory=list)
    factors: list[str] = Field(default_factory=list)
    source_experiment: str | None = None


class ExperimentProposal(BaseModel):
    id: str
    research_id: str
    intent: IntentType
    purpose: str
    fidelity: Fidelity
    backend: str
    parameters: dict[str, Any]
    estimated_cost: float
    risk: str
    safety_status: SafetyStatus
    approval_required: bool = False
    source_experiment: str | None = None
    controlled_factors: list[str] = Field(default_factory=list)


class ToolRequest(BaseModel):
    research_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
