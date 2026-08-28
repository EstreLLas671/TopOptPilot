// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
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
});