// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  engineeringInstallations: vi.fn(),
  engineeringRuntimeInstallations: vi.fn(),
  engineeringBundledRuntime: vi.fn(),
  engineeringProbe: vi.fn(),
  engineeringRun: vi.fn(),
  engineeringRunGet: vi.fn(),
  engineeringEvents: vi.fn(),
  engineeringStream: vi.fn(),
}));

vi.mock("./api", () => ({ api: apiMocks }));
vi.mock("./components/MonacoCodeEditor", () => ({ default: () => <div data-testid="monaco-editor" /> }));

import EngineeringWorkspace from "./features/engineering/EngineeringWorkspace";

describe("EngineeringWorkspace fast run event replay", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.engineeringInstallations.mockResolvedValue({ preference: "local-matlab", installations: [] });
    apiMocks.engineeringRuntimeInstallations.mockResolvedValue({ usable: false, runReady: false, installations: [] });
    apiMocks.engineeringBundledRuntime.mockResolvedValue({ state: "unavailable", usable: false, profileId: null, diagnostic: "standard package" });
    apiMocks.engineeringProbe.mockResolvedValue({ usable: true, version: "24.2", diagnostic: "MATLAB R2024b available" });
  });

  it("hydrates terminal progress from REST when the run finishes before WebSocket replay", async () => {
    const completedRun = {
      runId: "eng-fast",
      ownerType: "project",
      ownerId: "engineering-ui",
      lane: "python-fem",
      status: "completed",
      configDigest: "digest",
      metrics: { iteration: 30, iterations: 30, compliance: 281.0776, volumeFraction: 0.4, grayRatio: 0.1 },
      snapshots: [],
      files: [],
      provenance: { resultKind: "solver", backend: "python-fem" },
    };
    const close = vi.fn();
    apiMocks.engineeringRun.mockResolvedValue({ ...completedRun, status: "queued" });
    apiMocks.engineeringRunGet.mockResolvedValue(completedRun);
    apiMocks.engineeringEvents.mockResolvedValue({
      runId: completedRun.runId,
      events: [{
        type: "progress",
        iteration: 30,
        metrics: { iteration: 30, compliance: 281.0776, volumeFraction: 0.4, grayRatio: 0.1 },
      }],
    });
    apiMocks.engineeringStream.mockReturnValue({ close });

    render(
      <EngineeringWorkspace
        health={null}
        onError={() => undefined}
        onResearchBaseline={async () => undefined}
      />,
    );

    const lane = screen.getByRole("combobox", { name: "执行后端" }) as HTMLSelectElement;
    await waitFor(() => expect(lane.disabled).toBe(false));
    await userEvent.selectOptions(lane, "python-fem");
    await userEvent.click(screen.getByRole("button", { name: "开始优化" }));
    await waitFor(() => expect(apiMocks.engineeringEvents).toHaveBeenCalledWith("eng-fast"));
    await userEvent.click(screen.getByRole("tab", { name: "迭代可视化" }));

    expect(await screen.findByText("1 / 1")).toBeTruthy();
    expect(close).toHaveBeenCalledTimes(1);
  });
});
