import { describe, expect, it } from "vitest";
import { solverLaneLabel, workspaceLabel } from "./workspace";

describe("TopOptPilot workspace contract", () => {
  it("keeps the two user-facing workspaces explicit", () => {
    expect(workspaceLabel("basic-implementation")).toBe("基础实现");
    expect(workspaceLabel("deep-optimization")).toBe("深度优化");
  });
  it("does not collapse solver lanes into one MATLAB status", () => {
    expect(solverLaneLabel("local-matlab")).toBe("本机 MATLAB");
    expect(solverLaneLabel("matlab-mcp")).toBe("MATLAB MCP");
  });
});
