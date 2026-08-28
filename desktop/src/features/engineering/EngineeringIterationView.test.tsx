// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
  beforeEach(() => {
    artifactMocks.engineeringArtifactBuffer.mockReset();
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      configurable: true,
      value: vi.fn(() => null),
    });
  });

  it("shows real console state and deterministic progress before the first snapshot", () => {
    render(<EngineeringIterationView run={{ ...run, metrics: { iteration: 12 } }} maxIterations={60} events={[{
      type: "console",
      text: "Iteration 12: compliance=8.42",
    }]}/>);

    expect(screen.queryByText("等待真实 MATLAB 迭代快照")).toBeNull();
    expect(screen.queryByText(/真实命令行输出会同步显示/)).toBeNull();
    expect(screen.getByText("MATLAB 优化正在运行")).toBeTruthy();
    expect(screen.getByText("真实迭代 12 / 60")).toBeTruthy();
    expect(screen.getByText("Iteration 12: compliance=8.42")).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "真实优化进度" }).getAttribute("aria-valuenow")).toBe("20");
  });

  it("renders the real MATLAB density payload referenced by the progress event", async () => {
    artifactMocks.engineeringArtifactBuffer.mockResolvedValue(
      float32([0.1, 0.2, 0.8, 0.9]),
    );

    render(<EngineeringIterationView run={run} maxIterations={60} events={[{
      type: "progress",
      iteration: 1,
      metrics: { compliance: 12.5, volumeFraction: 0.4, grayRatio: 0.25 },
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
    expect(screen.getByText("0.2500")).toBeTruthy();
    expect(screen.queryByText(/占位/)).toBeNull();
  });

  it("shows interactive 3D density and stress while preserving the raw MATLAB render", async () => {
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:matlab-iteration-1"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
    artifactMocks.engineeringArtifactBuffer.mockImplementation(
      async (_runId: string, relativePath: string) => {
        if (relativePath.endsWith(".png")) return new Uint8Array([137, 80, 78, 71]).buffer;
        if (relativePath.includes("stress")) return float32([1, 2, 8, 9, 1.5, 2.5, 7.5, 8.5]);
        return float32([0.1, 0.2, 0.8, 0.9, 0.15, 0.25, 0.75, 0.85]);
      },
    );

    render(<EngineeringIterationView run={run} maxIterations={60} events={[{
      type: "progress",
      iteration: 1,
      metrics: { compliance: 12.5, volumeFraction: 0.4, grayRatio: 0.25 },
      snapshot: {
        densityPath: "snapshots/iter_0001_density.bin",
        stressPath: "snapshots/iter_0001_stress.bin",
        renderPath: "snapshots/iter_0001_matlab.png",
        shape: [2, 2, 2],
        dimension: "3d",
        densitySha256: "b".repeat(64),
        stressSha256: "d".repeat(64),
        renderSha256: "c".repeat(64),
      },
    }]}/>);

    expect(await screen.findByAltText("MATLAB 第 1 轮真实 3D 拓扑迭代图")).toBeTruthy();
    expect(screen.getByRole("button", { name: "MATLAB 原图" }).classList.contains("active")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "3D 密度" }));
    expect(await screen.findByLabelText("可旋转缩放的三维密度场")).toBeTruthy();
    expect(screen.getByRole("button", { name: "3D 密度" }).classList.contains("active")).toBe(true);
    expect(screen.getByRole("button", { name: "重置三维视角" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "真实曲面" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "单元网格" }));
    expect(screen.getByRole("button", { name: "单元网格" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "真实曲面" }).getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(screen.getByRole("button", { name: "3D 应力" }));
    expect(await screen.findByLabelText("可旋转缩放的三维 Von Mises 应力场")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "MATLAB 原图" }));
    const image = await screen.findByAltText("MATLAB 第 1 轮真实 3D 拓扑迭代图");
    expect(image.getAttribute("src")).toBe("blob:matlab-iteration-1");
    expect(artifactMocks.engineeringArtifactBuffer).toHaveBeenCalledWith(
      "eng-real-matlab",
      "snapshots/iter_0001_matlab.png",
    );
    expect(screen.getByText(/MATLAB 原始逐轮渲染/)).toBeTruthy();
  });
});
