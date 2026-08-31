"""Public data contracts shared by Streamlit, API and the research core."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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


class AgentRole(str, Enum):
    RESEARCH_LEAD = "RESEARCH_LEAD"
    GUIDE = "GUIDE"
    HYPOTHESIS = "HYPOTHESIS"
    EXPERIMENT_PLANNER = "EXPERIMENT_PLANNER"
    EXPERIMENT_EXECUTOR = "EXPERIMENT_EXECUTOR"
    INDEPENDENT_REVIEWER = "INDEPENDENT_REVIEWER"
    REPORT_WRITER = "REPORT_WRITER"


class SubagentStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReviewVerdict(str, Enum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


# Public V6 name retained separately from the persistence field name.
SubagentVerdict = ReviewVerdict


class SolverVariant(str, Enum):
    REFERENCE_CPU = "reference_cpu"
    OPTIMIZED_CPU = "optimized_cpu"
    PARALLEL_CPU = "parallel_cpu"
    MEX = "mex"
    GPU = "gpu"


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
    MATLAB_INFRASTRUCTURE = "MATLAB_INFRASTRUCTURE"


class SafetyStatus(str, Enum):
    PASS = "PASS"
    REJECTED = "REJECTED"
    PENDING_HUMAN_APPROVAL = "PENDING_HUMAN_APPROVAL"


class TerminationReason(str, Enum):
    GOAL_ACHIEVED = "GOAL_ACHIEVED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    PLATEAU = "PLATEAU"
    USER_STOPPED = "USER_STOPPED"


class SubagentTask(BaseModel):
    id: str
    research_id: str
    role: AgentRole
    objective: str
    status: SubagentStatus = SubagentStatus.QUEUED
    evidence_ids: list[str] = Field(default_factory=list)
    proposal_id: str | None = None


class ExperimentHypothesis(BaseModel):
    id: str
    research_id: str
    round_number: int = Field(ge=1)
    statement: str
    competing: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: str = "ACTIVE"


class ControlledComparison(BaseModel):
    experiment_ids: list[str] = Field(min_length=2)
    parameter_differences: dict[str, Any] = Field(default_factory=dict)
    controlled: bool
    deterministic_delta: dict[str, float | int | None] = Field(default_factory=dict)


class ArtifactLineage(BaseModel):
    id: str
    research_id: str
    experiment_id: str | None = None
    artifact_type: str
    path: str | None = None
    sha256: str | None = None
    parents: list[str] = Field(default_factory=list)


class BudgetSpec(BaseModel):
    total: int = Field(default=12, ge=1)
    f0: int = Field(default=6, ge=0)
    f1: int = Field(default=4, ge=0)
    f2: int = Field(default=2, ge=0)
    f3: int = Field(default=1, ge=0)


class AgentSettings(BaseModel):
    """Non-sensitive defaults for newly created Pi sessions."""

    model: str = Field(default="qwen3.7-plus", min_length=1, max_length=120)
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        min_length=8,
        max_length=500,
    )
    timeout_seconds: int = Field(default=120, ge=5, le=600)
    max_retries: int = Field(default=3, ge=0, le=10)
    safe_mode: bool = True


class ComputeSettings(BaseModel):
    matlab_root: str | None = Field(default=None, max_length=500)
    python_workers: int = Field(default=2, ge=1, le=32)
    matlab_timeout_seconds: int = Field(default=600, ge=30, le=7200)
    matlab_retry_count: int = Field(default=1, ge=0, le=5)


class NewResearchSettings(BaseModel):
    mode: str = Field(default="COPILOT", pattern="^(COPILOT|AUTONOMOUS)$")
    budget_total: int = Field(default=12, ge=1, le=10000)
    budgets: BudgetSpec = Field(default_factory=BudgetSpec)
    constraints: dict[str, Any] = Field(
        default_factory=lambda: {"volume_fraction": 0.4, "gray_max": 0.05, "connected": True}
    )
    material: dict[str, float] = Field(default_factory=lambda: {"E": 1.0, "nu": 0.3})
    experiment: dict[str, Any] = Field(
        default_factory=lambda: {
            "mesh_level": "coarse",
            "parameters": {"volfrac": 0.4, "rmin": 1.5, "penal": 3.0, "beta": 1.0, "max_iter": 80},
        }
    )


class DataSettings(BaseModel):
    # This only selects the root for the *next* desktop start.  It never moves data.
    next_data_dir: str | None = Field(default=None, max_length=500)
    # Result-cache location. Changing it migrates existing cache files at save time;
    # None keeps the default <data_dir>/cache directory.
    cache_dir: str | None = Field(default=None, max_length=500)

class CustomThemeSettings(BaseModel):
    accent: str = Field(default="#2e73ca", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_hover: str = Field(default="#245da5", pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(default="#f4f7fb", pattern=r"^#[0-9a-fA-F]{6}$")
    surface: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    elevated: str = Field(default="#f8fbff", pattern=r"^#[0-9a-fA-F]{6}$")
    text: str = Field(default="#24344d", pattern=r"^#[0-9a-fA-F]{6}$")
    muted_text: str = Field(default="#6f8095", pattern=r"^#[0-9a-fA-F]{6}$")
    border: str = Field(default="#dce5ef", pattern=r"^#[0-9a-fA-F]{6}$")
    success: str = Field(default="#23835c", pattern=r"^#[0-9a-fA-F]{6}$")
    warning: str = Field(default="#b56b17", pattern=r"^#[0-9a-fA-F]{6}$")
    danger: str = Field(default="#c64242", pattern=r"^#[0-9a-fA-F]{6}$")
    chart: str = Field(default="#2e73ca", pattern=r"^#[0-9a-fA-F]{6}$")
    chart_grid: str = Field(default="#cbd7e5", pattern=r"^#[0-9a-fA-F]{6}$")
    volume_background: str = Field(default="#f1f5fa", pattern=r"^#[0-9a-fA-F]{6}$")
    contrast: int = Field(default=100, ge=80, le=140)


class AppSettings(BaseModel):
    """Persisted, non-secret application preferences.

    API keys deliberately do not appear in this model. They are read only from the
    process environment at the moment a connection is tested or a session starts.
    """

    locale: str = Field(default="zh-CN", pattern="^(zh-CN|en-US)$")
    ui_density: str = Field(default="standard", pattern="^(compact|standard|comfortable)$")
    startup_behavior: str = Field(default="resume_last", pattern="^(resume_last|research_list)$")
    theme: str = Field(default="light", pattern="^(light|dark|system|custom)$")
    custom_theme: CustomThemeSettings = Field(default_factory=CustomThemeSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    compute: ComputeSettings = Field(default_factory=ComputeSettings)
    new_research: NewResearchSettings = Field(default_factory=NewResearchSettings)
    data: DataSettings = Field(default_factory=DataSettings)
    time_seconds: float | None = Field(default=None, gt=0)


class ResearchCreate(BaseModel):
    name: str = Field(default="MBB Beam", min_length=1, max_length=120)
    goal: str = "Minimize compliance while satisfying constraints."
    description: str | None = Field(default=None, max_length=4000)
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
    field_sources: dict[str, str] = Field(default_factory=dict)

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
    fidelity: str = "F0 - 2D Coarse"
    mesh_level: str = "coarse"
    backend: Literal["python", "python3d", "matlab"] = "python"
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
    decision_source: str = "HUMAN"
    intent_source: str = "HUMAN"
    policy_version: str | None = None
    model: str | None = None
    provider: str | None = None
    session_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    knowledge_ids: list[str] = Field(default_factory=list)
    subagent_task_ids: list[str] = Field(default_factory=list)
    solver_variant: str = "auto"
    acceleration_mode: str = "auto"
    review_verdict: str | None = None
    human_decision: str | None = None

    @model_validator(mode="after")
    def validate_fidelity_backend(self) -> "ExperimentCreate":
        code = str(self.fidelity).strip().split(maxsplit=1)[0]
        expected = {"F0": "python", "F1": "python", "F2": "python3d", "F3": "matlab"}.get(code)
        if expected is None:
            raise ValueError("fidelity must start with F0, F1, F2, or F3")
        if self.backend != expected:
            raise ValueError(f"{code} requires backend={expected}; received backend={self.backend}")
        return self


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
    # The public API caller may identify the two supported local clients for
    # audit provenance, but cannot impersonate an internal Pi process.
    source: Literal["API", "TOPoptctl"] = "API"


class SubagentDispatchRequest(BaseModel):
    role: AgentRole
    objective: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    proposal_id: str | None = None


class KnowledgeDocument(BaseModel):
    id: str
    locale: str
    category: str
    title: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    content: str
    version: str = "1.0"


class SolverCapability(BaseModel):
    fidelity: Fidelity
    dimension: int
    mesh_level: str
    backend: str = "matlab"
    variants: list[str] = Field(default_factory=lambda: ["reference_cpu"])
    selected_variant: str = "reference_cpu"
    acceleration_mode: str = "cpu"
    available: bool = False
