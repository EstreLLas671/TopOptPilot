export type Locale = "zh-CN" | "en-US";
export interface BackendInfo { port: number; token: string }
export interface EventRecord { id: number; kind: string; title: string; body: string; created_at: string; experiment_id?: string; payload?: Record<string, unknown> }
export interface Experiment {
  id: string; status: string; fidelity: string; backend: string; progress: number;
  current_iteration: number; parameters: Record<string, unknown>; purpose: string;
  result?: { objective?: { compliance?: number }; constraints?: Record<string, number>;
    quality?: { gray_ratio?: number; connected_components?: number };
    solver?: Record<string, unknown>; artifacts?: { density?: unknown[]; history?: Array<Record<string, number>> } };
  error?: string;
}
export interface Decision { id: string; status: string; reason: string; risk: string; experiment_id?: string; proposal: { parameters?: Record<string, unknown>; fidelity?: string } }
export interface Research {
  id: string; name: string; goal: string; locale: Locale; status: string; mode: string;
  constraints: Record<string, unknown>; budget_total: number; budget_used: number;
  experiments: Experiment[]; events: EventRecord[]; decisions: Decision[];
  best_experiment?: Experiment; termination_reason?: string;
}
export interface MatlabHealth { state: string; server_version: string; matlab_root?: string; process_running: boolean; last_error?: string }
