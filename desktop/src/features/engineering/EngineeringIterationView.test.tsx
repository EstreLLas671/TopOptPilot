// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EngineeringRun } from "../../types";

const artifactMocks = vi.hoisted(() => ({
  engineeringArtifactBuffer: vi.fn(),
}));

vi.mock("../../backend-artifact", () => artifactMocks);

import EngineeringIterationView from "./EngineeringIterationView";

function float32(values: number[]): ArrayBuffer {
  const bytes = new Uint8Array(values.length * 4);
  const view = new DataView(bytes.buffer);
  values.forEach((value, index) => view.setFloat32(index * 4, value, true));
  return bytes.buffer;
}

const run: EngineeringRun = {
  runId: "eng-real-matlab",
  ownerType: "engineering_run",
  ownerId: "engineering",
  lane: "local-matlab",
  status: "running",
  configDigest: "a".repeat(64),
  metrics: {},
  snapshots: [],
  files: [],
  provenance: { resultKind: "solver" },
};

describe("EngineeringIterationView", () => {
  afterEach(cleanup);

  it("renders the real MATLAB density payload referenced by the progress event", async () => {
    artifactMocks.engineeringArtifactBuffer.mockResolvedValue(
      float32([0.1, 0.2, 0.8, 0.9]),
    );

    render(<EngineeringIterationView run={run} events={[{
      type: "progress",
      iteration: 1,
      metrics: { compliance: 12.5, volumeFraction: 0.4 },
      snapshot: {
        densityPath: "snapshots/iter_0001_density.bin",
        stressPath: null,
        shape: [2, 2],
        dimension: "2d",
        densitySha256: "b".repeat(64),
      },
    }]}/>);

    await waitFor(() => {
      expect(artifactMocks.engineeringArtifactBuffer).toHaveBeenCalledWith(
        "eng-real-matlab",
        "snapshots/iter_0001_density.bin",
      );
      expect(screen.getByLabelText("密度场").querySelectorAll("span")).toHaveLength(4);
    });
    expect(screen.getByText(/第 1 轮 · 2D/)).toBeTruthy();
    expect(screen.queryByText(/占位/)).toBeNull();
  });

  it("shows the real per-iteration MATLAB render as the default 3D view", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:matlab-iteration-1"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    artifactMocks.engineeringArtifactBuffer.mockImplementation(
      async (_runId: string, relativePath: string) => relativePath.endsWith(".png")
        ? new Uint8Array([137, 80, 78, 71]).buffer
        : float32([0.1, 0.2, 0.8, 0.9, 0.15, 0.25, 0.75, 0.85]),
    );

    render(<EngineeringIterationView run={run} events={[{
      type: "progress",
      iteration: 1,
      metrics: { compliance: 12.5, volumeFraction: 0.4 },
      snapshot: {
        densityPath: "snapshots/iter_0001_density.bin",
        stressPath: null,
        renderPath: "snapshots/iter_0001_matlab.png",
        shape: [2, 2, 2],
        dimension: "3d",
        densitySha256: "b".repeat(64),
        renderSha256: "c".repeat(64),
      },
    }]}/>);

    const image = await screen.findByAltText("MATLAB 第 1 轮真实 3D 拓扑迭代图");
    expect(image.getAttribute("src")).toBe("blob:matlab-iteration-1");
    expect(artifactMocks.engineeringArtifactBuffer).toHaveBeenCalledWith(
      "eng-real-matlab",
      "snapshots/iter_0001_matlab.png",
    );
    expect(screen.getByText(/MATLAB 原始逐轮渲染/)).toBeTruthy();
  });
});