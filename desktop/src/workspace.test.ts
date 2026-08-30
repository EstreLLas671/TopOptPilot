import { describe, expect, it } from "vitest";
import { solverLaneLabel, workspaceLabel } from "./workspace";

describe("TopOptPilot workspace contract", () => {
  it("keeps the two user-facing workspaces explicit", () => {
    expect(workspaceLabel("engineering")).toBe("工程开发");
    expect(workspaceLabel("research")).toBe("AI 科研");
  });
  it("does not collapse solver lanes into one MATLAB status", () => {
    expect(solverLaneLabel("local-matlab")).toBe("本机 MATLAB");
    expect(solverLaneLabel("matlab-mcp")).toBe("MATLAB MCP");
  });
});