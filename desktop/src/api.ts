import { invoke } from "@tauri-apps/api/core";
import type { AppSettings, BackendInfo, EngineeringRun, GeometryPreview, KnowledgeEntry, Locale, MatlabHealth, Research, SettingsDiagnostics, SolverCapabilities, SubagentTask, SystemHealth } from "./types";

let backend: BackendInfo | null = null;

export async function initializeBackend(): Promise<BackendInfo> {
  if (backend) return backend;
  if (import.meta.env.VITE_API_URL) {
    backend = { port: Number(new URL(import.meta.env.VITE_API_URL).port), token: import.meta.env.VITE_API_TOKEN || "" };
    return backend;
  }
  // A cold PyInstaller one-file extraction can take >20 s while Defender scans it.
  for (let attempt = 0; attempt < 240; attempt++) {
    try {
      const value = await invoke<BackendInfo | null>("backend_info");
      if (value?.port) { backend = value; return value; }
    } catch { /* sidecar is still starting */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Desktop backend did not become ready");
}

function base(): string { if (!backend) throw new Error("Backend not initialized"); return `http://127.0.0.1:${backend.port}`; }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  await initializeBackend();
  let lastError: unknown;
  // The handshake can precede Uvicorn's accept loop by a fraction of a second,
  // and Defender may briefly hold the extracted executable on a cold start.
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const response = await fetch(base() + path, { ...init, headers: { "Content-Type": "application/json",
        "X-TopOptPilot-Token": backend!.token, ...(init.headers || {}) } });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
      return response.json();
    } catch (reason) {
      lastError = reason;
      if (reason instanceof Error && !/Failed to fetch|NetworkError|Load failed/i.test(reason.message)) throw reason;
      await new Promise(resolve => setTimeout(resolve, Math.min(1000, 150 + attempt * 75)));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Desktop backend request failed");
}

async function download(path:string,filename:string):Promise<void>{
  await initializeBackend();
  const response=await fetch(base()+path,{headers:{"X-TopOptPilot-Token":backend!.token}});
  if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||response.statusText);
  const url=URL.createObjectURL(await response.blob()),anchor=document.createElement("a");
  anchor.href=url;anchor.download=filename;document.body.appendChild(anchor);anchor.click();anchor.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}

async function requestBuffer(path:string):Promise<ArrayBuffer>{
  await initializeBackend();
  const response=await fetch(base()+path,{headers:{"X-TopOptPilot-Token":backend!.token}});
  if(!response.ok)throw new Error((await response.json().catch(()=>({}))).detail||response.statusText);
  return response.arrayBuffer();
}

export const api = {
  projectPickFolder: () => invoke<string | null>("project_pick_folder"),
  readDroppedImages: (paths: string[]) => invoke<import("./types").DroppedImageData[]>("read_dropped_images", { paths }),
  projectOpen: (root: string) => invoke<import("./types").ProjectOpen>("project_open", { root }),
  projectList: (root: string) => invoke<import("./types").ProjectListing>("project_list_summary", { root }),
  projectRead: (root: string, relativePath: string) => invoke<import("./types").ProjectFile>("project_read", { root, relativePath }),
  projectSave: (root: string, relativePath: string, content: string, expectedSha256?: string) => invoke<import("./types").ProjectFile>("project_save", { root, relativePath, content, expectedSha256 }),
  projectCreate: (root: string, relativePath: string, content = "") => invoke<import("./types").ProjectFile>("project_create", { root, relativePath, content }),
  projectRename: (root: string, from: string, to: string) => invoke<void>("project_rename", { root, from, to }),
  projectSearch: (root: string, query: string) => invoke<import("./types").ProjectEntry[]>("project_search", { root, query }),
  patchPreview: (root: string, proposal: import("./types").PatchProposal) => invoke<import("./types").PatchPreviewResult>("patch_preview", { root, proposal }),
  patchApply: (root: string, proposal: import("./types").PatchProposal, approvalToken: string) => invoke<import("./types").ProjectFile[]>("patch_apply", { root, proposal, approvalToken }),
  engineeringPatch: (data: object) => request<import("./types").PatchProposal>("/api/engineering/assistant/patch", { method: "POST", body: JSON.stringify(data) }),
  engineeringChat: (data: object) => request<{reply: string; source: string; actions: Array<Record<string, unknown>>; contextDigest: string}>("/api/engineering/assistant/chat", { method: "POST", body: JSON.stringify(data) }),
  conversationList: (scope: "engineering" | "research", ownerId: string) => request<import("./types").Conversation[]>("/api/conversations?scope=" + scope + "&owner_id=" + encodeURIComponent(ownerId)),
  conversationCreate: (scope: "engineering" | "research", ownerId: string, title = "新对话") => request<import("./types").Conversation>("/api/conversations", { method: "POST", body: JSON.stringify({ scope, ownerId, title }) }),
  conversationRename: (id: string, title: string) => request<import("./types").Conversation>("/api/conversations/" + encodeURIComponent(id), { method: "PATCH", body: JSON.stringify({ title }) }),
  conversationDelete: (id: string) => request<{deleted:boolean;id:string}>("/api/conversations/" + encodeURIComponent(id), { method: "DELETE" }),
  conversationMessages: (id: string, afterSeq = 0) => request<import("./types").ConversationMessage[]>("/api/conversations/" + encodeURIComponent(id) + "/messages?after_seq=" + afterSeq),
  conversationMessage: (id: string, data: object) => request<import("./types").ConversationMessage>("/api/conversations/" + encodeURIComponent(id) + "/messages", { method: "POST", body: JSON.stringify(data) }),
  conversationAttachment: (id: string, data: object) => request<import("./types").ConversationAttachment>("/api/conversations/" + encodeURIComponent(id) + "/attachments", { method: "POST", body: JSON.stringify(data) }),
  health: () => request<SystemHealth>("/api/health"),
  listResearch: (archived = false) => request<Research[]>(`/api/research?archived=${archived ? "true" : "false"}`),
  archiveResearch: (id: string) => request<Research>(`/api/research/${encodeURIComponent(id)}?confirm=true`, { method: "DELETE" }),
  restoreResearch: (id: string) => request<Research>(`/api/research/${encodeURIComponent(id)}/restore`, { method: "POST" }),
  getResearch: (id: string) => request<Research>(`/api/research/${id}`),
  researchArtifacts: (id: string) => request<{researchId:string; experiments:Array<{experimentId:string; status:string; fidelity:string; backend:string; provenance:Record<string,string>; files:Array<{relativePath:string; sha256:string; mediaType:string; sizeBytes:number}>; metrics:Record<string,number|null>}>}>(`/api/research/${id}/artifacts`),
  researchEvents: (id: string, after = 0) => request<Array<Record<string, unknown>>>("/api/research/" + id + "/events?after=" + after),
  researchOptimizationConfig: (id: string) => request<import("./optimization-config").OptimizationConfig>("/api/researches/" + encodeURIComponent(id) + "/optimization-config"),
  saveResearchOptimizationConfig: (id: string, config: import("./optimization-config").OptimizationConfig) => request<import("./optimization-config").OptimizationConfig>("/api/researches/" + encodeURIComponent(id) + "/optimization-config", { method: "PUT", body: JSON.stringify(config) }),
  saveResearchGoal: (id: string, goal: string) => request<Research>("/api/researches/" + encodeURIComponent(id) + "/goal", { method: "PUT", body: JSON.stringify({ goal }) }),
  saveResearchHypothesis: (id: string, hypothesis: string) => request<Research>("/api/researches/" + encodeURIComponent(id) + "/hypothesis", { method: "PUT", body: JSON.stringify({ hypothesis }) }),
  applyResearchSuggestion: (id: string, action: import("./types").ResearchStateAction) => request<{research:Research;optimizationConfig?:import("./optimization-config").OptimizationConfig|null}>("/api/researches/" + encodeURIComponent(id) + "/apply-suggestion", { method: "POST", body: JSON.stringify(action) }),
  researchVisionChat: (id: string, message: string, attachmentIds: string[]) => request<{reply:string;source:string;contextDigest:string;actions:import("./types").ResearchStateAction[]}>("/api/research/" + encodeURIComponent(id) + "/vision-chat", { method: "POST", body: JSON.stringify({ message, attachmentIds }) }),
  researchChat: (id: string, message: string, selectedExperiment?: string) => request<{reply:string;source:string;contextDigest:string;actions:import("./types").ResearchStateAction[]}>("/api/research/" + encodeURIComponent(id) + "/chat", { method: "POST", body: JSON.stringify({ message, selectedExperiment }) }),
  researchSuggestionExtract: (id:string, sourceId:string, content:string) => request<{reply:string;sourceId:string;actions:import("./types").ResearchStateAction[]}>(`/api/research/${encodeURIComponent(id)}/suggestions/extract`, { method:"POST", body:JSON.stringify({sourceId,content}) }),
  researchPareto: (id: string) => request<Array<Record<string,unknown>>>(`/api/research/${id}/pareto`),
  researchCompare: (id: string, a: string, b: string) => request<Record<string,unknown>>(`/api/research/${id}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  researchFromEngineeringRun: (runId: string, data: object) => request<Research>(`/api/research/from-engineering-run/${encodeURIComponent(runId)}`, { method: "POST", body: JSON.stringify(data) }),
  researchImportEngineeringScheme: (researchId: string, schemeId: string) => request<{research:Research;optimizationConfig:import("./optimization-config").OptimizationConfig;baseline:import("./types").ImportedEngineeringBaseline}>(`/api/research/${encodeURIComponent(researchId)}/engineering-baselines`, { method: "POST", body: JSON.stringify({ schemeId }) }),
  researchVisualization: (researchId:string, experimentId:string) => request<import("./types").ResearchVisualizationManifest>(`/api/research/${encodeURIComponent(researchId)}/experiments/${encodeURIComponent(experimentId)}/visualization`),
  researchVisualizationField: (researchId:string, experimentId:string, field:"density"|"stress") => requestBuffer(`/api/research/${encodeURIComponent(researchId)}/experiments/${encodeURIComponent(experimentId)}/visualization/${field}`),
  researchReportExport: (researchId:string, data:{name:string;outputDirectory:string;formats:Array<"markdown"|"pdf">;overwrite:boolean}) => request<{markdownPath:string|null;pdfPath:string|null;assetDirectory:string;files:Array<{path:string;sizeBytes:number;sha256:string}>}>(`/api/research/${encodeURIComponent(researchId)}/reports/export`, { method: "POST", body: JSON.stringify(data) }),
  compare: (id:string,a:string,b:string) => request<Record<string,unknown>>(`/api/research/${id}/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`),
  createResearch: (data: object) => request<Research>("/api/research", { method: "POST", body: JSON.stringify(data) }),
  previewGuide: (text:string,locale:Locale) => request<Record<string,any>>("/api/guide", {method:"POST",body:JSON.stringify({text,locale})}),
  guide: (id:string,text:string) => request<Record<string,any>>(`/api/research/${id}/guide`, {method:"POST",body:JSON.stringify({text})}),
  agentTasks: (id:string) => request<SubagentTask[]>(`/api/research/${id}/agent-tasks`),
  knowledgeSearch: (query:string,locale:Locale,category?:string) => request<{items:KnowledgeEntry[];categories:Array<{category:string;count:number}>}>(`/api/knowledge/search?q=${encodeURIComponent(query)}&locale=${locale}${category?`&category=${encodeURIComponent(category)}`:""}`),
  knowledgeGet: (id:string,locale:Locale) => request<KnowledgeEntry>(`/api/knowledge/${encodeURIComponent(id)}?locale=${locale}`),
  solverCapabilities: () => request<SolverCapabilities>("/api/solvers/capabilities"),
  previewGeometry: (data:object,signal?:AbortSignal) => request<GeometryPreview>("/api/solvers/geometry-preview", {method:"POST",body:JSON.stringify(data),signal}),
  autonomous: (id: string) => request<Research>(`/api/research/${id}/autonomous`, { method: "POST" }),
  stopAutonomous: (id: string) => request<Research>(`/api/research/${encodeURIComponent(id)}/autonomous/stop`, { method: "POST" }),
  confirmResearchCandidatePlan: (id:string, preferredProposalId:string) => request<Research>(`/api/research/${encodeURIComponent(id)}/candidate-plan/confirm`, { method:"POST", body:JSON.stringify({ preferredProposalId }) }),
  finishResearch: (id:string) => request<Research>(`/api/research/${encodeURIComponent(id)}/finish`, { method:"POST" }),
  researchReportPreview: (id:string) => request<{markdown:string;markdownPath:string;pdfPath:string}>(`/api/research/${encodeURIComponent(id)}/reports/preview`),
  researchRuns: (id:string) => request<import("./types").ResearchRun[]>(`/api/research/${encodeURIComponent(id)}/runs`),
  researchFidelityStageDecision: (id: string, action: "REPEAT_STAGE" | "ADVANCE_STAGE" | "APPROVE_FINAL", selectedExperimentId?:string) => request<Research>(`/api/research/${encodeURIComponent(id)}/fidelity-stage-decision`, { method: "POST", body: JSON.stringify({ action, selectedExperimentId }) }),
  command: (id: string, text: string, selected_experiment?: string) => request<{ok:boolean;message:string;action:string;data:Record<string,unknown>}>(`/api/research/${id}/commands`, { method: "POST", body: JSON.stringify({ text, selected_experiment }) }),
  approve: (id: string) => request(`/api/decision/${id}/approve`, { method: "POST" }),
  reject: (id: string) => request(`/api/decision/${id}/reject`, { method: "POST" }),
  editDecision: (id: string, parameters: object) => request(`/api/decision/${id}/edit`, { method: "POST", body: JSON.stringify({ parameters }) }),
  why: (id: string) => request<{reason:string}>(`/api/decision/${id}/why`),
  setLocale: (id: string, locale: Locale) => request<Research>(`/api/research/${id}/locale`, { method: "PATCH", body: JSON.stringify({ locale }) }),
  matlabHealth: () => request<MatlabHealth>("/api/matlab/health"),
  restartMatlab: () => request<MatlabHealth>("/api/matlab/restart", { method: "POST" }),
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (settings: object) => request<AppSettings>("/api/settings", { method: "PATCH", body: JSON.stringify({ settings }) }),
  setAgentKey: (apiKey: string) => request<{configured:boolean;source:string}>("/api/settings/agent-key", { method: "POST", body: JSON.stringify({ api_key: apiKey }) }),
  deleteAgentKey: () => request<{deleted:boolean;source:string}>("/api/settings/agent-key", { method: "DELETE" }),
  testAgent: () => request<{ok:boolean;status:string;model:string;error?:string}>("/api/settings/test-agent", { method: "POST" }),
  restartPi: () => request("/api/settings/restart-pi", { method: "POST" }),
  diagnostics: () => request<SettingsDiagnostics>("/api/settings/diagnostics"),
  engineeringHealth: () => request<{status:string; service:string; version:string; capabilities:{localMatlab:string; compiledRuntime:string}; python:{mode:"source"|"packaged";version:string;bundled:boolean}}>("/api/engineering/health"),
  engineeringEnvironment: () => request<import("./types").EngineeringEnvironment>("/api/engineering/environment"),
  engineeringEnvironmentRefresh: () => request<import("./types").EngineeringEnvironment>("/api/engineering/environment/refresh", { method: "POST" }),
  engineeringInstallations: () => request<{preference:string; installations:Array<{executable?:string; release?:string; version?:string; source?:string; probeState?:string; diagnostic?:string|null}>}>("/api/engineering/matlab/installations"),
  engineeringRuntimeInstallations: () => request<{usable:boolean; runReady:boolean; installations:Array<{release?:string; version?:string; path?:string; source?:string; usable:boolean; reason?:string; runReady:boolean; runReason?:string; profileId?:string|null; solverExecutable?:string|null}>}>("/api/engineering/runtime/installations"),
  engineeringProbe: (executable: string, release = "") => request<{usable:boolean; version?:string; diagnostic:string; error?:Record<string, unknown>}>("/api/engineering/matlab/probe", { method: "POST", body: JSON.stringify({ executable, release }) }),
  engineeringPreference: (preference: "local-matlab" | "compiled-runtime") => request<{preference:string}>("/api/engineering/matlab/preference", { method: "POST", body: JSON.stringify({ preference }) }),
  engineeringRuntimeProbe: (root: string, solverExecutable: string) => request<{state:string; root:string; dllPath?:string; solverExecutable:string; profileId:string; usable:boolean; diagnostic:string}>("/api/engineering/runtime/probe", { method: "POST", body: JSON.stringify({ root, solverExecutable }) }),
  engineeringBundledRuntime: () => request<{state:string; root?:string; dllPath?:string; solverExecutable?:string; profileId:string|null; usable:boolean; diagnostic:string}>("/api/engineering/runtime/bundled"),
  engineeringRun: (data: object) => request<EngineeringRun>("/api/engineering/runs", { method: "POST", body: JSON.stringify(data) }),
  engineeringRunGet: (id: string) => request<EngineeringRun>(`/api/engineering/runs/${id}`),
  engineeringComparisonSchemes: () => request<import("./types").EngineeringComparisonScheme[]>("/api/engineering/comparison-schemes"),
  engineeringComparisonScheme: (id: string) => request<import("./types").EngineeringComparisonScheme>(`/api/engineering/comparison-schemes/${encodeURIComponent(id)}`),
  engineeringComparisonSchemeCreate: (runId: string, name?: string) => request<import("./types").EngineeringComparisonScheme>("/api/engineering/comparison-schemes", { method: "POST", body: JSON.stringify({ runId, name }) }),
  engineeringComparisonSchemeDelete: (id: string) => request<{deleted:boolean; id:string}>(`/api/engineering/comparison-schemes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  engineeringCancel: (id: string) => request<EngineeringRun>(`/api/engineering/runs/${id}/cancel`, { method: "POST" }),
  engineeringEvents: (id: string) => request<{runId:string; events:Array<Record<string,unknown>>}>(`/api/engineering/runs/${id}/events`),
  engineeringRuns: (projectId?: string) => request<{runs: EngineeringRun[]; nextCursor: number | null}>("/api/engineering/runs" + (projectId ? "?project_id=" + encodeURIComponent(projectId) : "")),
  engineeringConsole: (id: string, afterSeq = 0) => request<{runId:string; events:Array<Record<string,unknown>>}>("/api/engineering/runs/" + id + "/console?after_seq=" + afterSeq),
  engineeringReport: (id: string, name: string, outputDirectory?: string) => request<{relativePath:string; exportedPath?:string; sha256:string; mediaType:string; sizeBytes:number}>(`/api/engineering/runs/${id}/report`, { method: "POST", body: JSON.stringify({ name, outputDirectory: outputDirectory || null }) }),
  terminalStart: (data: object) => request<{sessionId:string; status:string}>("/api/engineering/terminal/start", { method: "POST", body: JSON.stringify(data) }),
  terminalCommand: (sessionId: string, command: string) => request<{queued:boolean; id:number; command:string}>(`/api/engineering/terminal/command?session_id=${encodeURIComponent(sessionId)}`, { method: "POST", body: JSON.stringify({ command }) }),
  terminalPoll: (sessionId: string) => request<{sessionId:string; status:string; results:Array<Record<string,unknown>>}>(`/api/engineering/terminal/${encodeURIComponent(sessionId)}`),
  terminalStop: (sessionId: string) => request<{sessionId:string; status:string}>(`/api/engineering/terminal/stop?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" }),
  engineeringStream: (id: string, onEvent: (event: Record<string, unknown>) => void): WebSocket => {
    if (!backend) throw new Error("Backend not initialized");
    const socket = new WebSocket(`ws://127.0.0.1:${backend.port}/api/engineering/runs/${id}/stream?token=${encodeURIComponent(backend.token)}`);
    socket.onmessage = message => { try { onEvent(JSON.parse(message.data)); } catch { /* ignore malformed event */ } };
    return socket;
  },
  clearCache: () => request<{message:string}>("/api/settings/clear-cache", { method: "POST", body: JSON.stringify({confirm:true}) }),
  downloadReport:(id:string,format:"markdown"|"pdf")=>download(format==="pdf"?`/api/report/${id}/pdf`:`/api/report/${id}`,`${id}_report.${format==="pdf"?"pdf":"md"}`),
  async stream(id: string): Promise<WebSocket> {
    if (!backend) throw new Error("Backend not initialized");
    const value = await request<{ticket:string}>(`/api/research/${id}/stream-ticket`, {method:"POST"});
    return new WebSocket(`ws://127.0.0.1:${backend.port}/api/research/${id}/stream?ticket=${encodeURIComponent(value.ticket)}`);
  }
};
