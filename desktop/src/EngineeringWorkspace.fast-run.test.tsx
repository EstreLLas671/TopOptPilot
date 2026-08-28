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
  conversationList: vi.fn(),
  conversationCreate: vi.fn(),
  conversationMessages: vi.fn(),
  conversationMessage: vi.fn(),
  conversationDelete: vi.fn(),
  conversationAttachment: vi.fn(),
}));

vi.mock("./api", () => ({ api: apiMocks }));
vi.mock("./components/MonacoCodeEditor", () => ({ default: () => <div data-testid="monaco-editor" /> }));

import EngineeringWorkspace from "./features/engineering/EngineeringWorkspace";

describe("EngineeringWorkspace fast run event replay", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    apiMocks.engineeringInstallations.mockResolvedValue({ preference: "local-matlab", installations: [] });
    apiMocks.engineeringRuntimeInstallations.mockResolvedValue({ usable: false, runReady: false, installations: [] });
    apiMocks.engineeringBundledRuntime.mockResolvedValue({ state: "unavailable", usable: false, profileId: null, diagnostic: "standard package" });
    apiMocks.engineeringProbe.mockResolvedValue({ usable: true, version: "24.2", diagnostic: "MATLAB R2024b available" });
    apiMocks.conversationList.mockResolvedValue([]);
    apiMocks.conversationCreate.mockResolvedValue({
      id: "conversation-1", scope: "engineering", ownerId: "engineering-unbound",
      title: "工程对话", createdAt: "2026-08-26T00:00:00Z", updatedAt: "2026-08-26T00:00:00Z",
    });
    apiMocks.conversationMessages.mockResolvedValue([]);
  });

  it("uses all available center height for chat and only adds the compact assistant on other tabs", async () => {
    const view = render(
      <EngineeringWorkspace
        health={null}
        onError={() => undefined}
        onResearchBaseline={async () => undefined}
      />,
    );

    expect(await screen.findByPlaceholderText("询问当前工程、参数或结果…")).toBeTruthy();
    const shell = view.container.querySelector(".engineering-center-shell");
    expect(shell?.classList.contains("chat-layout")).toBe(true);
    expect(shell?.classList.contains("has-compact-assistant")).toBe(false);
    expect(view.container.querySelector(".engineering-composer")).toBeNull();

    await userEvent.click(screen.getByRole("tab", { name: /^代码/ }));
    expect(shell?.classList.contains("has-compact-assistant")).toBe(true);
    expect(view.container.querySelector(".engineering-composer")).toBeTruthy();

    await userEvent.click(screen.getByRole("tab", { name: "聊天" }));
    expect(await screen.findByPlaceholderText("询问当前工程、参数或结果…")).toBeTruthy();
    expect(shell?.classList.contains("chat-layout")).toBe(true);
    expect(view.container.querySelector(".engineering-composer")).toBeNull();
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

    await userEvent.click(screen.getByRole("button", { name: "打开参数配置" }));
    const lane = screen.getByLabelText("求解链路") as HTMLSelectElement;
    await waitFor(() => expect(lane.disabled).toBe(false));
    await userEvent.selectOptions(lane, "python-fem");
    await userEvent.click(screen.getByRole("button", { name: "应用配置" }));
    await userEvent.click(screen.getByRole("button", { name: "开始优化" }));    await waitFor(() => expect(apiMocks.engineeringEvents).toHaveBeenCalledWith("eng-fast"));
    await userEvent.click(screen.getByRole("tab", { name: "迭代可视化" }));

    expect(await screen.findByText("1 / 1")).toBeTruthy();
    expect(close).toHaveBeenCalledTimes(1);
  });
});
