import { beforeEach, describe, expect, it, vi } from "vitest";

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

import { api } from "./api";
import type { PatchProposal } from "./types";

describe("patch approval API", () => {
  beforeEach(() => invoke.mockReset());

  it("passes the one-time approval token to patch_apply", async () => {
    const proposal: PatchProposal = {
      projectId: "project-1",
      baseDigest: "a".repeat(64),
      files: [{ relativePath: "solver.m", beforeDigest: "a".repeat(64), unifiedDiff: "diff" }],
    };
    invoke.mockResolvedValue([]);

    await api.patchApply("C:/project", proposal, "preview-token");

    expect(invoke).toHaveBeenCalledWith("patch_apply", {
      root: "C:/project",
      proposal,
      approvalToken: "preview-token",
    });
  });
});
