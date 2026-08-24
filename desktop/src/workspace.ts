export type WorkspaceMode = "engineering" | "research";
export type AssistantMode = WorkspaceMode;
export const workspaceLabel = (mode: WorkspaceMode) => mode === "engineering" ? "工程开发" : "AI 科研";
export const solverLaneLabel = (lane: string) => ({
  "local-matlab": "本机 MATLAB",
  "compiled-runtime": "编译 Runtime",
  "python-fem": "Python FEM",
  "matlab-mcp": "MATLAB MCP",
}[lane] ?? lane);