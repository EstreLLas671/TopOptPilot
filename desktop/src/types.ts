import type { OptimizationConfig } from "./optimization-config";

export type Locale = "zh-CN" | "en-US";
export interface BackendInfo { port: number; token: string }
export interface ProjectEntry { relative_path: string; kind: string; size_bytes: number }
export interface ProjectListing { entries: ProjectEntry[]; truncated: boolean; skippedDirectories: number; skippedLinks: number }
export interface ProjectFile { relative_path: string; content: string; sha256: string }
export interface ProjectOpen { root: string; projectId: string }
export interface PatchProposal { projectId: string; baseDigest: string; files: Array<{ relativePath: string; beforeDigest: string; unifiedDiff: string }> }
export interface PatchPreviewResult { approvalToken: string; proposal: PatchProposal }
export interface PatchApproval extends PatchPreviewResult { root: string }
export interface EventRecord { id: number; event_id?:string; type?:string; source?:string; kind: string; title: string; body: string; created_at: string; timestamp?:string; experiment_id?: string; payload?: Record<string, any> }
export interface StressMetric {
  maximum_von_mises?: number | null;
  stress_unit?: "MPa" | "normalized" | null;
  stress_unit_trusted?: boolean;
  allowable_stress_mpa?: number;
  passes_allowable_stress?: boolean;
  stress_evidence_id?: string;
  stress_unavailable_reason?: string | null;
}
export interface Experiment {
  id: string; status: string; fidelity: string; backend: string; progress: number;
  current_iteration: number; parameters: Record<string, unknown>; purpose: string; round_number?:number;
  decision_source?:string; intent_source?:string; policy_version?:string; model?:string; provider?:string;
  session_id?:string; evidence_ids?:string[]; result_source?:"LIVE_REAL_RUN"|"CACHED_REAL_RESULT"|"VERIFIED_REPLAY";
  knowledge_ids?:string[]; subagent_task_ids?:string[]; solver_variant?:string; acceleration_mode?:string;
  solver_sha256?:string; task_hash?:string; review_verdict?:string; human_decision?:string;
  result?: { objective?: { compliance?: number }; constraints?: Record<string, number>;
    quality?: { gray_ratio?: number; connected_components?: number } & StressMetric;
    evaluation?: Record<string, any>; solver?: Record<string, any>; artifacts?: { density?: unknown[]; history?: Array<Record<string, number>> } };
  error?: string;
}
export interface Decision { id: string; status: string; reason: string; risk: string; source?:string; evidence_ids?:string[]; experiment_id?: string; proposal: { parameters?: Record<string, unknown>; fidelity?: string } }
export interface ResearchProposal {
  id:string; intent:string; purpose:string; fidelity:string; backend:string;
  parameters:Record<string,unknown>; estimated_cost?:number; risk:string;
  safety_status:string; controlled_factors:string[]; status:string; experiment_id?:string|null;
}
export interface Research {
  id: string; name: string; goal: string; hypothesis?: string | null; locale: Locale; status: string; mode: string;
  constraints: Record<string, any>; archived_at?: string | null; geometry?:Record<string,any>; material?:Record<string,any>; loads?:Record<string,any>[]; boundary_conditions?:Record<string,any>;
  contract?:Record<string,any>; defaults?:Record<string,any>; budgets?:Record<string,number>; current_round?:number; budget_total: number; budget_used: number;
  experiments: Experiment[]; events: EventRecord[]; decisions: Decision[]; proposals?:ResearchProposal[];
  subagent_tasks?:SubagentTask[]; hypotheses?:Hypothesis[]; artifact_lineage?:ArtifactLineage[];
  best_experiment?: Experiment; termination_reason?: string; active_run_id?:string;
  workflow?: ResearchWorkflowProgress;
}
export type ResearchWorkflowStage = "idle" | "context" | "planning" | "approval" | "experiments" | "comparison" | "selection" | "diagnosis" | "next_round" | "completed" | "failed";
export interface ResearchWorkflowStep {
  id:string; label:string; status:"pending"|"active"|"completed"|"failed";
  summary?:string; result?:string; reflection?:string; evidenceIds:string[]; experimentIds:string[];
  nextAction?:string; completedAt?:string;
}
export interface ResearchWorkflowProgress {
  round:number; stage:ResearchWorkflowStage; percent:number; steps:ResearchWorkflowStep[];
  budgetUsed:number; budgetTotal:number;
}
export interface ResearchRun {
  id:string; research_id:string; ordinal:number;
  status:"READY"|"RUNNING"|"STOPPING"|"STOPPED"|"STOP_FAILED"|"COMPLETED"|"ARCHIVED";
  budget_total:number; budget_used:number; termination_reason?:string|null;
  created_at:string; stopped_at?:string|null; archived_at?:string|null;
}
export interface ResearchStageGate {
  eventId:string; stageCode:"STEP1"|"STEP2"|"STEP3"|"STEP4"; internalFidelity:string; round:number;
  experimentIds:string[]; bestExperimentId?:string; result:Record<string,unknown>;
}
export interface ImportedEngineeringBaseline {
  schemeId:string; name:string; runId:string; configDigest:string;
  metrics:Record<string,number|null>; provenance:Record<string,string>; importedFrom:"engineering-comparison-scheme";
}
export interface ResearchVisualizationManifest {
  researchId:string; experimentId:string; dimension:"2d"|"3d"; shape:[number,number,number];
  encoding:"float32-le"; order:"F"; hasStress:boolean;
  history:Array<Record<string,number>>; metrics:{compliance?:number|null;volumeFraction?:number|null;grayRatio?:number|null;connectedComponents?:number|null};
  config:Record<string,unknown>; backend:string; fidelity:string; status:string; evidenceIds:string[]; resultSource?:string;
}
export interface SubagentTask { id:string; role:string; objective:string; status:string; result?:{text?:string}; error?:string; proposal_id?:string; evidence_ids?:string[] }
export interface Hypothesis { id:string; round_number:number; statement:string; competing?:string[]; evidence_ids?:string[]; status:string }
export interface ResearchStateAction {
  type: "apply_research_state";
  messageId?: string;
  goal?: string;
  hypothesis?: string;
  optimizationConfig?: OptimizationConfig;
  changedFields: Array<"goal" | "hypothesis" | "optimizationConfig">;
  rationale?: string;
}
export interface ArtifactLineage { id:string; artifact_type:string; path?:string; sha256?:string; parents?:string[] }
export interface KnowledgeEntry { id:string; locale:Locale; category:string; title:string; summary:string; tags:string[]; version:string; citation:string; content?:string }
export interface SolverCapabilities { matlab:MatlabHealth; runtime:Record<string,any>; fidelities:Array<Record<string,any>>; strict_matlab:boolean; python_fallback:boolean }
export interface GeometryPreview { dimension:number; grid:number[]; domain_mask:boolean[][]|boolean[][][]; support_nodes:number[][]; load_nodes:number[][]; bc_type:string; generated_by:"MATLAB"; matlab_version?:string; completed_at?:string }
export interface MatlabHealth { state: string; server_version: string; matlab_root?: string; process_running: boolean; last_error?: string; capabilities?:Record<string,any> }
export interface BackendComponent { status:string; model?:string; provider?:string; version?:string; root?:string; last_error?:string; [key:string]:unknown }
export interface SystemHealth { status:string; version:string; components:Record<string,BackendComponent> }
export interface AppSettings {
  locale: Locale; ui_density: "compact" | "standard" | "comfortable"; startup_behavior: "resume_last" | "research_list";
  theme: "light" | "dark" | "system" | "custom";
  custom_theme: {
    accent:string; accent_hover?:string; background:string; surface:string; elevated?:string;
    text:string; muted_text?:string; border?:string; success?:string; warning?:string; danger?:string;
    chart?:string; chart_grid?:string; volume_background?:string; contrast?:number;
  };
  api_key_status: "environment" | "credential_manager" | "not_configured"; updated_at?: string;
  agent: { model:string; base_url:string; timeout_seconds:number; max_retries:number; safe_mode:boolean };
  compute: { matlab_root?:string|null; python_workers:number; matlab_timeout_seconds:number; matlab_retry_count:number };
  new_research: { mode:string; budget_total:number; budgets:Record<string,number>; constraints:Record<string,unknown>; material:Record<string,number>; experiment:Record<string,unknown> };
  data: { next_data_dir?:string|null; cache_dir?:string|null; cache_migration?:{moved_files:number;skipped_existing:number;cache_dir:string} };
}
export interface SettingsDiagnostics { data_dir:string; database:string; cache_dir?:string; cache_bytes:number; log_dir:string; free_disk_bytes:number; sidecar_port?:string; version:string; health: Record<string, unknown> }
export interface EngineeringEnvironment {
  cached: boolean; checkedAt?: string;
  matlab: { path: string; release: string; version: string; probeState: "ready" | "failed" | "unknown"; diagnostic?: string };
  python: { mode: "packaged" | "source"; version: string };
  runtime: { state: "optional" | "ready" | "incompatible" | "not_configured"; count?: number };
}
export type EngineeringRunStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export interface EngineeringArtifactRef { relativePath: string; sha256: string; mediaType: string; sizeBytes: number }
export interface EngineeringRun {
  runId: string; ownerType: string; ownerId: string;
  lane: "local-matlab" | "compiled-runtime" | "python-fem" | "matlab-mcp";
  status: EngineeringRunStatus; configDigest: string;
  metrics: Record<string, number | null>; snapshots: EngineeringArtifactRef[];
  files: EngineeringArtifactRef[]; provenance: Record<string, string>;
  error?: { code: string; source: string; message: string; retryable: boolean };
}
export interface EngineeringComparisonScheme {
  id: string; name: string; runId: string; configDigest: string; createdAt: string;
  config: Record<string, unknown>; run: EngineeringRun | null;
  integrity: "verified" | "failed" | "missing"; integrityFailures: string[];
}

export interface Conversation {
  id: string; scope: "engineering" | "research"; ownerId: string; title: string;
  createdAt: number; updatedAt: number;
}
export interface ConversationAttachment {
  id: string; fileName?: string; mediaType: string;
  sizeBytes: number; sha256?: string;
}
export interface DroppedImageData {
  fileName: string; mediaType: string;
  sizeBytes: number; dataBase64: string; sha256: string;
}
export interface ConversationMessage {
  id: string; seq: number; role: "user" | "assistant" | "system" | "progress";
  content: string; attachmentIds: string[]; attachments: ConversationAttachment[];
  source?: string | null; status?: string | null; createdAt: number;
}
