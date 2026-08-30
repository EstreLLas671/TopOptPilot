// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  initializeBackend: vi.fn(), engineeringHealth: vi.fn(), settings: vi.fn(),
  listResearch: vi.fn(), engineeringEnvironment: vi.fn(), getResearch: vi.fn(),
}));
vi.mock("./api", () => ({ initializeBackend: mocks.initializeBackend, api: mocks }));
vi.mock("./theme", () => ({ applyTheme: vi.fn() }));
vi.mock("./SettingsWorkspace", () => ({ default: () => null }));
vi.mock("./features/engineering/EngineeringWorkspace", () => ({ default: () => <div>engineering</div> }));
vi.mock("./features/research/ResearchWorkspace", () => ({
  default: (props: any) => <div>
    <span data-testid="selected-research">{props.selected?.id || "none"}</span>
    <span data-testid="active-experiment">{props.active?.id || "none"}</span>
    <button onClick={() => void props.onSelect("R-A")}>选择 A</button>
    <button onClick={() => void props.onSelect("R-B")}>选择 B</button>
    <button onClick={() => props.onSelectExperiment({ id: "E-B", status: "SUCCESS" })}>选择实验 B</button>
  </div>,
}));

import V2App from "./V2App";

const summary = (id: string) => ({ id, name: id, goal: "goal", status: "READY", budget_total: 3, budget_used: 0, mode: "COPILOT", experiments: [], decisions: [], events: [] });

describe("V2App Research selection races", () => {
  beforeEach(() => {
    mocks.initializeBackend.mockResolvedValue({});
    mocks.engineeringHealth.mockResolvedValue({ status: "ok", service: "sidecar", version: "2", capabilities: {} });
    mocks.settings.mockResolvedValue({ locale: "zh-CN", ui_density: "comfortable", agent: { safe_mode: true }, new_research: { budget_total: 3, mode: "COPILOT", constraints: {} } });
    mocks.listResearch.mockResolvedValue([summary("R-A"), summary("R-B")]);
    mocks.engineeringEnvironment.mockResolvedValue({ matlab: {}, runtime: {} });
    mocks.getResearch.mockResolvedValueOnce(summary("R-A"));
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("accepts only the latest Research response and preserves experiment selection on same-id refresh", async () => {
    const pending = new Map<string, Array<(value: any) => void>>();
    mocks.getResearch.mockImplementation((id: string) => new Promise(resolve => {
      const values = pending.get(id) || [];
      values.push(resolve); pending.set(id, values);
    }));
    render(<V2App/>);
    await waitFor(() => expect(screen.getByTestId("selected-research").textContent).toBe("R-A"));
    fireEvent.click(screen.getByRole("button", { name: "AI 科研" }));
    fireEvent.click(screen.getByRole("button", { name: "选择 A" }));
    fireEvent.click(screen.getByRole("button", { name: "选择 B" }));
    await waitFor(() => expect(pending.get("R-B")?.length).toBe(1));
    pending.get("R-B")?.shift()?.(summary("R-B"));
    await waitFor(() => expect(screen.getByTestId("selected-research").textContent).toBe("R-B"));
    pending.get("R-A")?.shift()?.(summary("R-A"));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(screen.getByTestId("selected-research").textContent).toBe("R-B");

    fireEvent.click(screen.getByRole("button", { name: "选择实验 B" }));
    expect(screen.getByTestId("active-experiment").textContent).toBe("E-B");
    fireEvent.click(screen.getByRole("button", { name: "选择 B" }));
    await waitFor(() => expect(pending.get("R-B")?.length).toBe(1));
    pending.get("R-B")?.shift()?.({ ...summary("R-B"), experiments: [{ id: "E-B", status: "SUCCESS" }] });
    await waitFor(() => expect(screen.getByTestId("active-experiment").textContent).toBe("E-B"));
  });
});
