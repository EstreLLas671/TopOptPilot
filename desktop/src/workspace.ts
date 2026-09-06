export type WorkspaceMode = "basic-implementation" | "deep-optimization";
export type AssistantMode = WorkspaceMode;
export const workspaceLabel = (mode: WorkspaceMode) => mode === "basic-implementation" ? "基础实现" : "深度优化";
export const solverLaneLabel = (lane: string) => ({
  "local-matlab": "本机 MATLAB",
  "compiled-runtime": "编译 Runtime",
  "python-fem": "Python FEM",
  "matlab-mcp": "MATLAB MCP",
}[lane] ?? lane);
