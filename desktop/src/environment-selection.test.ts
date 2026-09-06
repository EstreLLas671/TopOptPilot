import { describe, expect, it } from "vitest";
import { selectDetectedEnvironment } from "./engineering-workspace";

describe("startup engineering environment selection", () => {
  it("selects a discovered MATLAB and only a run-ready Runtime profile", () => {
    const selected = selectDetectedEnvironment(
      {
        preference: "local-matlab",
        installations: [
          { release: "R2024b", version: "24.2", executable: "D:/MATLAB/R2024b/bin/matlab.exe", source: "registry", probeState: "unknown" },
        ],
      },
      {
        usable: true,
        runReady: true,
        installations: [
          { release: "R2024b", version: "24.2", path: "C:/Runtime/R2024b", source: "registry", usable: true, reason: "完整", runReady: true, runReason: "已验证", profileId: "runtime-1", solverExecutable: "C:/solver/TopOptSolver.exe" },
        ],
      },
    );

    expect(selected.matlabExecutable).toBe("D:/MATLAB/R2024b/bin/matlab.exe");
    expect(selected.matlabRelease).toBe("R2024b");
    expect(selected.runtimeProfileId).toBe("runtime-1");
    expect(selected.runtimeState).toBe("ready");
  });

  it("reports an installed but version-incompatible Runtime without making it runnable", () => {
    const selected = selectDetectedEnvironment(
      { preference: "local-matlab", installations: [] },
      {
        usable: true,
        runReady: false,
        installations: [
          { release: "R2025b", version: "25.2", path: "C:/Runtime/R2025b", source: "registry", usable: true, reason: "完整", runReady: false, runReason: "求解器为 R2024b", profileId: null, solverExecutable: null },
        ],
      },
    );

    expect(selected.matlabExecutable).toBe("");
    expect(selected.runtimeProfileId).toBe("");
    expect(selected.runtimeState).toBe("detected-incompatible");
    expect(selected.runtimeDiagnostic).toContain("R2024b");
  });
});
