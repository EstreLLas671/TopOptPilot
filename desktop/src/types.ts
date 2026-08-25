export type Locale = "zh-CN" | "en-US";
export interface BackendInfo { port: number; token: string }
export interface ProjectEntry { relative_path: string; kind: string; size_bytes: number }
export interface ProjectFile { relative_path: string; content: string; sha256: string }
export interface ProjectOpen { root: string; projectId: string }
export interface PatchProposal { projectId: string; baseDigest: string; files: Array<{ relativePath: string; beforeDigest: string; unifiedDiff: string }> }
export interface PatchPreviewResult { approvalToken: string; proposal: PatchProposal }
export interface PatchApproval extends PatchPreviewResult { root: string }
export interface EventRecord { id: number; event_id?:string; type?:string; source?:string; kind: string; title: string; body: string; created_at: string; timestamp?:string; experiment_id?: string; payload?: Record<string, any> }
export interface Experiment {
  id: string; status: string; fidelity: string; backend: string; progress: number;
  current_iteration: number; parameters: Record<string, unknown>; purpose: string; round_number?:number;
  decision_source?:string; intent_source?:string; policy_version?:string; model?:string; provider?:string;
  session_id?:string; evidence_ids?:string[]; result_source?:"LIVE_REAL_RUN"|"CACHED_REAL_RESULT"|"VERIFIED_REPLAY";
  knowledge_ids?:string[]; subagent_task_ids?:string[]; solver_variant?:string; acceleration_mode?:string;
  solver_sha256?:string; task_hash?:string; review_verdict?:string; human_decision?:string;
  result?: { objective?: { compliance?: number }; constraints?: Record<string, number>;
    quality?: { gray_ratio?: number; connected_components?: number };
    evaluation?: Record<string, any>; solver?: Record<string, any>; artifacts?: { density?: unknown[]; history?: Array<Record<string, number>> } };
  error?: string;
}
export interface Decision { id: string; status: string; reason: string; risk: string; source?:string; evidence_ids?:string[]; experiment_id?: string; proposal: { parameters?: Record<string, unknown>; fidelity?: string } }
export interface Research {
  id: string; name: string; goal: string; locale: Locale; status: string; mode: string;
  constraints: Record<string, any>; archived_at?: string | null; geometry?:Record<string,any>; material?:Record<string,any>; loads?:Record<string,any>[]; boundary_conditions?:Record<string,any>;
  contract?:Record<string,any>; budgets?:Record<string,number>; current_round?:number; budget_total: number; budget_used: number;
  experiments: Experiment[]; events: EventRecord[]; decisions: Decision[];
  subagent_tasks?:SubagentTask[]; hypotheses?:Hypothesis[]; artifact_lineage?:ArtifactLineage[];
  best_experiment?: Experiment; termination_reason?: string;
}
export interface SubagentTask { id:string; role:string; objective:string; status:string; result?:{text?:string}; error?:string; proposal_id?:string; evidence_ids?:string[] }
export interface Hypothesis { id:string; round_number:number; statement:string; competing?:string[]; evidence_ids?:string[]; status:string }
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
  custom_theme: { accent: string; background: string; surface: string; text: string };
  api_key_status: "environment" | "credential_manager" | "not_configured"; updated_at?: string;
  agent: { model:string; base_url:string; timeout_seconds:number; max_retries:number; safe_mode:boolean };
  compute: { matlab_root?:string|null; python_workers:number; matlab_timeout_seconds:number; matlab_retry_count:number };
  new_research: { mode:string; budget_total:number; budgets:Record<string,number>; constraints:Record<string,unknown>; material:Record<string,number>; experiment:Record<string,unknown> };
  data: { next_data_dir?:string|null; cache_dir?:string|null; cache_migration?:{moved_files:number;skipped_existing:number;cache_dir:string} };
}
export interface SettingsDiagnostics { data_dir:string; database:string; cache_dir?:string; cache_bytes:number; log_dir:string; free_disk_bytes:number; sidecar_port?:string; version:string; health: Record<string, unknown> }
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
