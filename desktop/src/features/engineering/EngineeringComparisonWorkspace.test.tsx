// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EngineeringComparisonScheme, EngineeringRun } from "../../types";

const apiMocks = vi.hoisted(() => ({
  engineeringComparisonSchemes: vi.fn(),
  engineeringComparisonScheme: vi.fn(),
  engineeringComparisonSchemeCreate: vi.fn(),
  engineeringComparisonSchemeDelete: vi.fn(),
  engineeringEvents: vi.fn(),
}));
const artifactMocks = vi.hoisted(() => ({ engineeringArtifactBuffer: vi.fn() }));
vi.mock("../../api", () => ({ api: apiMocks }));
vi.mock("../../backend-artifact", () => artifactMocks);

import EngineeringComparisonWorkspace from "./EngineeringComparisonWorkspace";

function float32(values: number[]): ArrayBuffer {
  const bytes = new Uint8Array(values.length * 4);
  const view = new DataView(bytes.buffer);
  values.forEach((value, index) => view.setFloat32(index * 4, value, true));
  return bytes.buffer;
}

function savedScheme(id: string, name: string): EngineeringComparisonScheme {
  const run: EngineeringRun = {
    runId: "run-" + id,
    ownerType: "engineering_run",
    ownerId: "engineering",
    lane: "local-matlab",
    status: "completed",
    configDigest: id.repeat(64).slice(0, 64),
    metrics: { compliance: id === "a" ? 12.5 : 10.2 },
    snapshots: [],
    files: [],
    provenance: { resultKind: "solver" },
  };
  return {
    id: "scheme-" + id,
    name,
    runId: run.runId,
    configDigest: run.configDigest,
    createdAt: "2026-08-26T00:00:00Z",
    config: { task: { geometry: { nelx: 2, nely: 2, nelz: 2 }, params: { volfrac: 0.4 } } },
    run,
    integrity: "verified",
    integrityFailures: [],
  };
}

function progress(runId: string) {
  return {
    runId,
    events: [{
      type: "progress",
      iteration: 1,
      metrics: { compliance: 12.5, volumeFraction: 0.4 },
      snapshot: {
        densityPath: "snapshots/iter_0001_density.bin",
        stressPath: "snapshots/iter_0001_stress.bin",
        shape: [2, 2, 2],
        dimension: "3d",
        densitySha256: "d".repeat(64),
        stressSha256: "s".repeat(64),
      },
    }],
  };
}

const schemeA = savedScheme("a", "方案 A");
const schemeB = savedScheme("b", "方案 B");

const current = { lane: "local-matlab" as const, nelx: 2, nely: 2, nelz: 2, volfrac: 0.4, maxIter: 60 };

describe("EngineeringComparisonWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.engineeringComparisonSchemes.mockResolvedValue([schemeA, schemeB]);
    apiMocks.engineeringComparisonScheme.mockImplementation(async (id: string) => id === schemeA.id ? schemeA : schemeB);
    apiMocks.engineeringEvents.mockImplementation(async (runId: string) => progress(runId));
    artifactMocks.engineeringArtifactBuffer.mockResolvedValue(float32([0.1, 0.2, 0.8, 0.9, 0.15, 0.25, 0.75, 0.85]));
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", { configurable: true, value: vi.fn(() => null) });
  });
  afterEach(cleanup);

  it("loads true events and compares two independently interactive 3D schemes", async () => {
    render(<EngineeringComparisonWorkspace current={current} run={schemeA.run} />);

    const rowA = await screen.findByRole("row", { name: /方案 A/ });
    fireEvent.click(rowA);
    const selector = await screen.findByRole("combobox", { name: "选择对照方案" });

    expect(apiMocks.engineeringEvents).toHaveBeenCalledWith(schemeA.runId);
    expect(within(selector).queryByRole("option", { name: "方案 A" })).toBeNull();
    expect(within(selector).getByRole("option", { name: "方案 B" })).toBeTruthy();
    expect(await screen.findByLabelText("可旋转缩放的三维密度场")).toBeTruthy();

    await userEvent.selectOptions(selector, schemeB.id);
    await waitFor(() => expect(apiMocks.engineeringEvents).toHaveBeenCalledWith(schemeB.runId));
    expect(await screen.findAllByLabelText("可旋转缩放的三维密度场")).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "重置三维视角" })).toHaveLength(2);

    const stressButtons = screen.getAllByRole("button", { name: "3D 应力" });
    expect(stressButtons).toHaveLength(2);
    fireEvent.click(stressButtons[0]);
    fireEvent.click(stressButtons[1]);
    expect(await screen.findAllByLabelText("可旋转缩放的三维 Von Mises 应力场")).toHaveLength(2);
  });
});