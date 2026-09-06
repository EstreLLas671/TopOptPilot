import { describe, expect, it } from "vitest";
import {
  acceptGeneratedPatch,
  acceptPatchApply,
  acceptPatchPreview,
  advancePatchPreviewContext,
  claimPatchApplyFlight,
  approvalTokenFor,
  type PatchPreviewContextInput,
} from "./engineering-workspace";
import type { PatchApproval, PatchPreviewResult, PatchProposal, ProjectFile } from "./types";

const proposal: PatchProposal = {
  projectId: "project-1",
  baseDigest: "a".repeat(64),
  files: [{
    relativePath: "solver.m",
    beforeDigest: "a".repeat(64),
    unifiedDiff: "@@ -1 +1 @@\n-old\n+new\n",
  }],
};

const approval: PatchApproval = {
  approvalToken: "preview-token",
  root: "C:/project",
  proposal,
};

describe("patch approval state", () => {
  it("keeps the token only for the exact previewed root and proposal", () => {
    expect(approvalTokenFor(approval, "C:/project", proposal)).toBe("preview-token");
    expect(approvalTokenFor(approval, "D:/project", proposal)).toBeNull();
    expect(approvalTokenFor(approval, "C:/project", {
      ...proposal,
      files: [{ ...proposal.files[0], unifiedDiff: "@@ -1 +1 @@\n-old\n+tampered\n" }],
    })).toBeNull();
    expect(approvalTokenFor(approval, "C:/project", {
      ...proposal,
      projectId: "project-2",
    })).toBeNull();
    expect(approvalTokenFor(approval, "C:/project", {
      ...proposal,
      baseDigest: "b".repeat(64),
    })).toBeNull();
  });

  it("clears the token when no approval is stored", () => {
    expect(approvalTokenFor(null, "C:/project", proposal)).toBeNull();
  });
});

describe("asynchronous patch preview", () => {
  const input: PatchPreviewContextInput = {
    root: "C:/project",
    projectId: "project-1",
    relativePath: "solver.m",
    fileDigest: "a".repeat(64),
    unifiedDiff: proposal.files[0].unifiedDiff,
    dirty: false,
    assistantInstruction: "improve solver",
  };
  const preview: PatchPreviewResult = {
    approvalToken: "preview-token",
    proposal,
  };

  it("accepts a response only while every captured context field is current", () => {
    const captured = advancePatchPreviewContext(null, input);
    expect(acceptPatchPreview(preview, captured, captured)).toEqual({ ...preview, root: input.root });

    const changed: PatchPreviewContextInput[] = [
      { ...input, root: "D:/project" },
      { ...input, projectId: "project-2" },
      { ...input, relativePath: "other.m" },
      { ...input, fileDigest: "b".repeat(64) },
      { ...input, unifiedDiff: "@@ -1 +1 @@\n-old\n+different\n" },
      { ...input, dirty: true },
    ];
    for (const latestInput of changed) {
      const latest = advancePatchPreviewContext(captured, latestInput);
      expect(acceptPatchPreview(preview, captured, latest)).toBeNull();
    }
  });

  it("rejects an old response even when changed context returns to the same values", () => {
    const captured = advancePatchPreviewContext(null, input);
    const changed = advancePatchPreviewContext(captured, {
      ...input,
      unifiedDiff: "@@ -1 +1 @@\n-old\n+temporary\n",
    });
    const restored = advancePatchPreviewContext(changed, input);

    expect(restored).toMatchObject(input);
    expect(restored.generation).toBeGreaterThan(captured.generation);
    expect(acceptPatchPreview(preview, captured, restored)).toBeNull();
  });
});

describe("asynchronous patch generation", () => {
  const input: PatchPreviewContextInput = {
    root: "C:/project",
    projectId: "project-1",
    relativePath: "solver.m",
    fileDigest: "a".repeat(64),
    unifiedDiff: "",
    dirty: false,
    assistantInstruction: "improve solver",
  };

  it("accepts generated output only for the latest matching request and response identity", () => {
    const captured = advancePatchPreviewContext(null, input);
    expect(acceptGeneratedPatch(proposal, captured, captured, 1, 1)).toEqual(proposal);

    const mismatches: PatchProposal[] = [
      { ...proposal, projectId: "project-2" },
      { ...proposal, baseDigest: "b".repeat(64) },
      { ...proposal, files: [{ ...proposal.files[0], relativePath: "other.m" }] },
      { ...proposal, files: [{ ...proposal.files[0], beforeDigest: "b".repeat(64) }] },
    ];
    for (const generated of mismatches) {
      expect(acceptGeneratedPatch(generated, captured, captured, 1, 1)).toBeNull();
    }
  });

  it("rejects generation after project, file, instruction, dirty, or ABA changes", () => {
    const captured = advancePatchPreviewContext(null, input);
    const changes: PatchPreviewContextInput[] = [
      { ...input, root: "D:/project" },
      { ...input, projectId: "project-2" },
      { ...input, relativePath: "other.m" },
      { ...input, fileDigest: "b".repeat(64) },
      { ...input, assistantInstruction: "different instruction" },
      { ...input, dirty: true },
    ];
    for (const change of changes) {
      const latest = advancePatchPreviewContext(captured, change);
      expect(acceptGeneratedPatch(proposal, captured, latest, 1, 1)).toBeNull();
    }
    const changed = advancePatchPreviewContext(captured, changes[2]);
    const restored = advancePatchPreviewContext(changed, input);
    expect(acceptGeneratedPatch(proposal, captured, restored, 1, 1)).toBeNull();
  });
  it("accepts only the latest same-context generation request", () => {
    const captured = advancePatchPreviewContext(null, input);
    const firstNonce = 1;
    const secondNonce = 2;

    expect(acceptGeneratedPatch(proposal, captured, captured, secondNonce, secondNonce)).toEqual(proposal);
    expect(acceptGeneratedPatch(proposal, captured, captured, firstNonce, secondNonce)).toBeNull();
  });
});

describe("asynchronous patch apply", () => {
  const input: PatchPreviewContextInput = {
    root: "C:/project",
    projectId: "project-1",
    relativePath: "solver.m",
    fileDigest: "a".repeat(64),
    unifiedDiff: proposal.files[0].unifiedDiff,
    dirty: false,
    assistantInstruction: "improve solver",
  };
  const applied: ProjectFile[] = [{
    relative_path: "solver.m",
    content: "new\n",
    sha256: "b".repeat(64),
  }];

  it("updates the selected file only for an unchanged latest apply context", () => {
    const captured = advancePatchPreviewContext(null, input);
    expect(acceptPatchApply(applied, captured, captured)).toEqual(applied);
    expect(acceptPatchApply(
      applied,
      captured,
      advancePatchPreviewContext(captured, { ...input, dirty: true }),
    )).toBeNull();
    expect(acceptPatchApply(
      [{ ...applied[0], relative_path: "other.m" }],
      captured,
      captured,
    )).toBeNull();
  });

  it("admits only one same-tick apply flight", () => {
    const flight = { current: false };

    expect(claimPatchApplyFlight(flight)).toBe(true);
    expect(claimPatchApplyFlight(flight)).toBe(false);

    flight.current = false;
    expect(claimPatchApplyFlight(flight)).toBe(true);
  });
});
