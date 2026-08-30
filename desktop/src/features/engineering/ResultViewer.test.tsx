// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
const artifactMocks = vi.hoisted(() => ({ text: vi.fn(), buffer: vi.fn() }));
vi.mock("../../backend-text", () => ({ engineeringArtifactText: artifactMocks.text }));
vi.mock("../../backend-artifact", () => ({ engineeringArtifactBuffer: artifactMocks.buffer }));
import type { EngineeringRun } from "../../types";
import ResultViewer, { ConvergenceChart } from "./ResultViewer";

afterEach(cleanup);

describe("engineering results metrics and convergence", () => {
  it("renders visible axes, ticks and centered plotting bounds", () => {
    const { container } = render(<ConvergenceChart points={[
      { iteration: 1, compliance: 20 },
      { iteration: 2, compliance: 14 },
      { iteration: 3, compliance: 11 },
    ]}/>);
    const chart = screen.getByLabelText("柔度收敛曲线");
    expect(chart.getAttribute("preserveAspectRatio")).toBe("xMidYMid meet");
    expect(container.querySelector(".chart-axis")).toBeTruthy();
    expect(screen.getByText("迭代")).toBeTruthy();
    expect(screen.getByText("柔度")).toBeTruthy();
    const points = container.querySelector(".chart-line")?.getAttribute("points") || "";
    expect(points).toContain("14,");
    expect(points).toContain("96,");
  });

  it("restores the true gray ratio in the result summary", () => {
    const run: EngineeringRun = {
      runId:"run-gray", ownerType:"engineering_run", ownerId:"engineering",
      lane:"local-matlab", status:"running", configDigest:"a".repeat(64),
      metrics:{ compliance:12.5, volumeFraction:0.4, grayRatio:0.1875 },
      snapshots:[], files:[], provenance:{ resultKind:"solver" },
    };
    render(<ResultViewer run={run} onError={() => undefined}/>);
    expect(screen.getByText("灰度率")).toBeTruthy();
    expect(screen.getByText("0.1875")).toBeTruthy();
  });

  it("reads one immutable result version once across parent rerenders", async () => {
    artifactMocks.text.mockImplementation(async (_runId: string, path: string) => {
      if (path === "result_manifest.json") return JSON.stringify({ shape: [2, 2], density_file: "density.bin" });
      if (path === "density.csv") return "0.1,0.2\n0.3,0.4\n";
      if (path === "history.json") return JSON.stringify([{ iteration: 1, compliance: 4 }]);
      return "";
    });
    artifactMocks.buffer.mockResolvedValue(new Float32Array([.1, .2, .3, .4]).buffer);
    const files = [
      { relativePath: "result_manifest.json", mediaType: "application/json", sizeBytes: 10, sha256: "1".repeat(64) },
      { relativePath: "density.csv", mediaType: "text/csv", sizeBytes: 10, sha256: "2".repeat(64) },
      { relativePath: "history.json", mediaType: "application/json", sizeBytes: 10, sha256: "3".repeat(64) },
    ];
    const run = { runId: "run-cache-once", ownerType: "engineering_run", ownerId: "engineering", lane: "local-matlab", status: "completed", configDigest: "a".repeat(64), metrics: {}, snapshots: [], files, provenance: { resultKind: "solver" } } as EngineeringRun;
    const view = render(<ResultViewer run={run} onError={() => undefined}/>);
    await waitFor(() => expect(screen.queryByText("正在读取真实结果制品…")).toBeNull());
    view.rerender(<ResultViewer run={{ ...run, files: [...files] }} onError={() => undefined}/>);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(artifactMocks.text).toHaveBeenCalledTimes(3);
    expect(artifactMocks.buffer).toHaveBeenCalledTimes(1);
  });
});
