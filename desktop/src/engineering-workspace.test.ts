import { describe, expect, it } from "vitest";
import {
  assistantConsentAfterAttempt,
  buildEngineeringRunRequest,
  buildEngineeringAssistantRequest,
  buildResearchBaselineRequest,
  formatTerminalResults,
  nextSolverLane,
  acceptRuntimeProbeResponse,
  claimRuntimeProbeFlight,
  bundledRuntimeProfile,
} from "./engineering-workspace";

describe("engineering workspace controller", () => {
  it("cycles only through human-controlled engineering lanes", () => {
    expect(nextSolverLane("python-fem")).toBe("local-matlab");
    expect(nextSolverLane("local-matlab")).toBe("compiled-runtime");
    expect(nextSolverLane("compiled-runtime")).toBe("python-fem");
  });

  it("builds a run request without exposing the research MATLAB MCP lane", () => {
    expect(buildEngineeringRunRequest("local-matlab", "project-123")).toMatchObject({
      lane: "local-matlab",
      ownerId: "project-123",
      task: { task_id: "idesktop-v2-ui", load_case: "cantilever" },
    });
  });

  it("binds compiled Runtime runs to the verified profile only", () => {
    expect(buildEngineeringRunRequest("compiled-runtime", "project-123", "runtime-profile-1")).toMatchObject({
      lane: "compiled-runtime",
      runtimeProfileId: "runtime-profile-1",
    });
    expect(() => buildEngineeringRunRequest("compiled-runtime", "project-123", "")).toThrow(/探测/);
    expect(buildEngineeringRunRequest("python-fem", "project-123", "stale-profile")).not.toHaveProperty("runtimeProfileId");
  });

  it("accepts a Runtime probe only when the captured lane and paths are still current", () => {
    const captured = { generation: 2, lane: "compiled-runtime" as const, root: "C:/runtime", solverExecutable: "C:/solver.exe" };
    expect(acceptRuntimeProbeResponse(captured, { ...captured }, "profile-1")).toBe("profile-1");
    expect(acceptRuntimeProbeResponse(captured, { ...captured, generation: 3 }, "profile-1")).toBeNull();

    expect(acceptRuntimeProbeResponse(captured, { ...captured, lane: "python-fem" }, "profile-1")).toBeNull();
    expect(acceptRuntimeProbeResponse(captured, { ...captured, root: "D:/runtime" }, "profile-1")).toBeNull();
    expect(acceptRuntimeProbeResponse(captured, { ...captured, solverExecutable: "D:/solver.exe" }, "profile-1")).toBeNull();
  });

  it("allows only one Runtime probe flight at a time", () => {
    const flight = { current: false };
    expect(claimRuntimeProbeFlight(flight)).toBe(true);
    expect(claimRuntimeProbeFlight(flight)).toBe(false);
    flight.current = false;
    expect(claimRuntimeProbeFlight(flight)).toBe(true);
  });
  it("uses only a ready and hash-verified bundled Runtime profile", () => {
    expect(bundledRuntimeProfile({ state: "ready", usable: true, profileId: "runtime-bundled" })).toBe("runtime-bundled");
    expect(bundledRuntimeProfile({ state: "unavailable", usable: false, profileId: null })).toBeNull();
    expect(bundledRuntimeProfile({ state: "ready", usable: false, profileId: "stale" })).toBeNull();
  });

  it("formats terminal results once and preserves errors", () => {
    expect(formatTerminalResults([
      { id: 1, status: "completed", output: "ans = 2" },
      { id: 2, status: "failed", error: "MATLAB stopped" },
    ])).toEqual(["ans = 2", "[failed] MATLAB stopped"]);
  });

  it("builds a research baseline only from completed solver evidence", () => {
    const run = {
      runId: "run-real",
      ownerType: "engineering-run",
      ownerId: "project-1",
      lane: "python-fem" as const,
      status: "completed" as const,
      configDigest: "a".repeat(64),
      metrics: {},
      snapshots: [],
      files: [{
        relativePath: "result.json",
        sha256: "b".repeat(64),
        mediaType: "application/json",
        sizeBytes: 10,
      }],
      provenance: { resultKind: "solver", backend: "python-fem" },
    };

    expect(buildResearchBaselineRequest(run, 8)).toEqual({
      name: "工程基线 · run-real",
      goal: "以工程运行 run-real 的真实求解证据为基线，经 Policy 审批后开展科研实验",
      budgetTotal: 8,
    });
    expect(() => buildResearchBaselineRequest({ ...run, status: "failed" }, 8)).toThrow(/completed/);
    expect(() => buildResearchBaselineRequest({ ...run, provenance: { resultKind: "demo", backend: "python-fem" } }, 8)).toThrow(/solver/);
  });

  it("requires explicit consent before building an external assistant request", () => {
    const file = { relative_path: "solver/main.m", content: "disp('ok')\n", sha256: "c".repeat(64) };

    expect(() => buildEngineeringAssistantRequest(
      "project-1", file, "Explain and improve this function", false,
    )).toThrow(/consent/);

    const request = buildEngineeringAssistantRequest(
      "project-1",
      file,
      "Explain and improve this function",
      true,
    );

    expect(request).toEqual({
      projectId: "project-1",
      relativePath: "solver/main.m",
      beforeDigest: "c".repeat(64),
      content: "disp('ok')\n",
      instruction: "Explain and improve this function",
      allowExternalSource: true,
    });
  });

  it("consumes source-sharing consent after every assistant attempt", () => {
    expect(assistantConsentAfterAttempt()).toBe(false);
  });
});
