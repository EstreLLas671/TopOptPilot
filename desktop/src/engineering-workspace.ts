import type { EngineeringRun, PatchApproval, PatchPreviewResult, PatchProposal, ProjectFile } from "./types";

export type EngineeringSolverLane = "python-fem" | "local-matlab" | "compiled-runtime";
export interface MatlabInstallation {
  release?: string;
  version?: string;
  executable?: string;
  source?: string;
  probeState?: string;
  diagnostic?: string | null;
}

export interface MatlabInstallationsPayload {
  preference: string;
  installations: MatlabInstallation[];
}

export interface RuntimeInstallation {
  release?: string;
  version?: string;
  path?: string;
  source?: string;
  usable: boolean;
  reason?: string;
  runReady: boolean;
  runReason?: string;
  profileId?: string | null;
  solverExecutable?: string | null;
}

export interface RuntimeInstallationsPayload {
  usable: boolean;
  runReady: boolean;
  installations: RuntimeInstallation[];
}

export interface DetectedEnvironmentSelection {
  matlabExecutable: string;
  matlabRelease: string;
  runtimeProfileId: string;
  runtimeState: "ready" | "detected-incompatible" | "not-detected";
  runtimeDiagnostic: string;
}

export function selectDetectedEnvironment(
  matlabPayload: MatlabInstallationsPayload,
  runtimePayload: RuntimeInstallationsPayload,
): DetectedEnvironmentSelection {
  const matlab = matlabPayload.installations.find(item => Boolean(item.executable));
  const runnableRuntime = runtimePayload.installations.find(
    item => item.runReady && Boolean(item.profileId),
  );
  if (runnableRuntime) {
    return {
      matlabExecutable: matlab?.executable || "",
      matlabRelease: matlab?.release || "",
      runtimeProfileId: runnableRuntime.profileId || "",
      runtimeState: "ready",
      runtimeDiagnostic: runnableRuntime.runReason || runnableRuntime.reason || "Runtime 已就绪",
    };
  }

  const detectedRuntime = runtimePayload.installations[0];
  return {
    matlabExecutable: matlab?.executable || "",
    matlabRelease: matlab?.release || "",
    runtimeProfileId: "",
    runtimeState: detectedRuntime ? "detected-incompatible" : "not-detected",
    runtimeDiagnostic: detectedRuntime?.runReason || detectedRuntime?.reason || "未检测到 MATLAB Runtime",
  };
}

export interface EngineeringRunRequest {
  lane: EngineeringSolverLane;
  ownerId: string;
  runtimeProfileId?: string;
  task: {
    task_id: string;
    load_case: string;
    geometry: { nelx: number; nely: number; nelz: number };
    params: { volfrac: number; penal: number; rmin: number; max_iter: number; min_iter: number; filter_strategy: string; accuracy: string };
  };
}

const laneOrder: EngineeringSolverLane[] = ["python-fem", "local-matlab", "compiled-runtime"];

export function nextSolverLane(lane: EngineeringSolverLane): EngineeringSolverLane {
  return laneOrder[(laneOrder.indexOf(lane) + 1) % laneOrder.length];
}

export function buildEngineeringRunRequest(lane: EngineeringSolverLane, ownerId: string, runtimeProfileId = ""): EngineeringRunRequest {
  if (lane === "compiled-runtime" && !runtimeProfileId) {
    throw new Error("运行编译 Runtime 前必须先完成 Runtime 与求解器探测");
  }
  return {
    lane,
    ownerId: ownerId || "engineering-ui",
    ...(lane === "compiled-runtime" ? { runtimeProfileId } : {}),
    task: {
      task_id: "topoptpilot-ui",
      load_case: "cantilever",
      geometry: { nelx: 30, nely: 15, nelz: 4 },
      params: { volfrac: 0.4, penal: 3, rmin: 1.5, max_iter: 60, min_iter: 10, filter_strategy: "fixed", accuracy: "standard" },
    },
  };
}

export interface RuntimeProbeContext {
  generation: number;
  lane: EngineeringSolverLane;

  root: string;
  solverExecutable: string;
}

export interface BundledRuntimeProbe {
  state: string;
  usable: boolean;
  profileId: string | null;
}

export function bundledRuntimeProfile(probe: BundledRuntimeProbe): string | null {
  return probe.state === "ready" && probe.usable && probe.profileId ? probe.profileId : null;
}

export function claimRuntimeProbeFlight(flight: { current: boolean }): boolean {
  if (flight.current) return false;
  flight.current = true;
  return true;
}

export function acceptRuntimeProbeResponse(
  captured: RuntimeProbeContext,
  latest: RuntimeProbeContext,
  profileId: string,
 ): string | null {
  if (!profileId || captured.generation !== latest.generation
      || captured.lane !== latest.lane
      || captured.root !== latest.root
      || captured.solverExecutable !== latest.solverExecutable) {
    return null;
  }
  return profileId;
}

export interface ResearchBaselineRequest {
  name: string;
  goal: string;
  budgetTotal: number;
}

export function buildResearchBaselineRequest(run: EngineeringRun, budgetTotal: number): ResearchBaselineRequest {
  if (run.status !== "completed") {
    throw new Error("Research baselines require a completed engineering run");
  }
  if (run.provenance.resultKind !== "solver" || !run.provenance.backend || !run.files.length) {
    throw new Error("Research baselines require real solver provenance and output files");
  }
  const normalizedBudget = Number.isFinite(budgetTotal) ? Math.max(1, Math.floor(budgetTotal)) : 12;
  return {
    name: `工程基线 · ${run.runId}`,
    goal: `以工程运行 ${run.runId} 的真实求解证据为基线，经 Policy 审批后开展科研实验`,
    budgetTotal: normalizedBudget,
  };
}
export interface EngineeringAssistantRequest {
  projectId: string;
  relativePath: string;
  beforeDigest: string;
  content: string;
  instruction: string;
  allowExternalSource: boolean;
}

export function buildEngineeringAssistantRequest(
  projectId: string,
  file: ProjectFile,
  instruction: string,
  allowExternalSource: boolean,
): EngineeringAssistantRequest {
  if (!allowExternalSource) {
    throw new Error("Explicit source-sharing consent is required");
  }
  return {
    projectId,
    relativePath: file.relative_path,
    beforeDigest: file.sha256,
    content: file.content,
    instruction: instruction.trim(),
    allowExternalSource,
  };
}

export function assistantConsentAfterAttempt(): false {
  return false;
}

export function approvalTokenFor(
  approval: PatchApproval | null,
  root: string,
  proposal: PatchProposal | null,
): string | null {
  if (!approval || !proposal || approval.root !== root) return null;
  const previewed = approval.proposal;
  if (previewed.projectId !== proposal.projectId
      || previewed.baseDigest !== proposal.baseDigest
      || previewed.files.length !== proposal.files.length) return null;
  const matches = previewed.files.every((file, index) => {
    const current = proposal.files[index];
    return file.relativePath === current.relativePath
      && file.beforeDigest === current.beforeDigest
      && file.unifiedDiff === current.unifiedDiff;
  });
  return matches ? approval.approvalToken : null;
}

export interface PatchPreviewContextInput {
  root: string;
  projectId: string;
  relativePath: string;
  fileDigest: string;
  unifiedDiff: string;
  dirty: boolean;
  assistantInstruction: string;
}

export interface PatchPreviewContext extends PatchPreviewContextInput {
  generation: number;
}

function samePatchPreviewContext(
  left: PatchPreviewContextInput,
  right: PatchPreviewContextInput,
): boolean {
  return left.root === right.root
    && left.projectId === right.projectId
    && left.relativePath === right.relativePath
    && left.fileDigest === right.fileDigest
    && left.unifiedDiff === right.unifiedDiff
    && left.dirty === right.dirty
    && left.assistantInstruction === right.assistantInstruction;
}

export function advancePatchPreviewContext(
  current: PatchPreviewContext | null,
  input: PatchPreviewContextInput,
): PatchPreviewContext {
  if (current && samePatchPreviewContext(current, input)) return current;
  return { ...input, generation: (current?.generation ?? 0) + 1 };
}

function currentPatchContext(
  captured: PatchPreviewContext,
  latest: PatchPreviewContext,
): boolean {
  return !latest.dirty
    && captured.generation === latest.generation
    && samePatchPreviewContext(captured, latest);
}

export function acceptGeneratedPatch(
  generated: PatchProposal,
  captured: PatchPreviewContext,
  latest: PatchPreviewContext,
  capturedNonce: number,
  latestNonce: number,
): PatchProposal | null {
  if (capturedNonce !== latestNonce
      || !currentPatchContext(captured, latest)
      || generated.projectId !== captured.projectId
      || generated.baseDigest !== captured.fileDigest
      || generated.files.length !== 1) return null;
  const file = generated.files[0];
  return file.relativePath === captured.relativePath
      && file.beforeDigest === captured.fileDigest
    ? generated
    : null;
}

export function claimPatchApplyFlight(flight: { current: boolean }): boolean {
  if (flight.current) return false;
  flight.current = true;
  return true;
}

export function acceptPatchApply(
  applied: ProjectFile[],
  captured: PatchPreviewContext,
  latest: PatchPreviewContext,
): ProjectFile[] | null {
  if (!currentPatchContext(captured, latest) || applied.length === 0) return null;
  return applied[0].relative_path === captured.relativePath ? applied : null;
}

export function acceptPatchPreview(
  preview: PatchPreviewResult,
  captured: PatchPreviewContext,
  latest: PatchPreviewContext,
): PatchApproval | null {
  if (!currentPatchContext(captured, latest)) return null;
  return {
    ...preview,
    root: captured.root,
  };
}

export function formatTerminalResults(results: Array<Record<string, unknown>>): string[] {
  return results.map(result => {
    const output = typeof result.output === "string" ? result.output : "";
    const error = typeof result.error === "string" ? result.error : "";
    if (error) return `[${String(result.status || "failed")}] ${error}`;
    return output || `[${String(result.status || "completed")}]`;
  });
}
