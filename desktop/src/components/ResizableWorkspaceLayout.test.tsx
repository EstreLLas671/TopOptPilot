// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import ResizableWorkspaceLayout from "./ResizableWorkspaceLayout";

function renderLayout() {
  return render(
    <ResizableWorkspaceLayout
      mode="engineering"
      left={<span>左栏内容</span>}
      leftHeader={<b>工程工作区</b>}
      center={<span>中栏内容</span>}
      right={<span>右栏内容</span>}
      bottom={<span>下栏内容</span>}
    />,
  );
}

describe("ResizableWorkspaceLayout", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(cleanup);

  it("uses only the five-track CSS variable grid and does not override it inline", () => {
    const { container } = renderLayout();
    const workspace = container.querySelector(".resizable-workspace") as HTMLElement;

    expect(workspace.style.gridTemplateColumns).toBe("");
    expect(workspace.style.getPropertyValue("--left-track")).toBe("280px");
    expect(workspace.style.getPropertyValue("--right-track")).toBe("380px");
  });

  it("independently hides and restores left, right, and bottom panels", () => {
    renderLayout();

    expect(screen.queryByText("下栏内容")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "显示底部面板" }));
    fireEvent.click(screen.getByRole("button", { name: "隐藏左侧项目栏" }));
    fireEvent.click(screen.getByRole("button", { name: "隐藏右侧检查器" }));
    fireEvent.click(screen.getByRole("button", { name: "隐藏底部面板" }));
    expect(screen.queryByText("左栏内容")).toBeNull();
    expect(screen.queryByText("右栏内容")).toBeNull();
    expect(screen.queryByText("下栏内容")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "显示左侧项目栏" }));
    fireEvent.click(screen.getByRole("button", { name: "显示右侧检查器" }));
    fireEvent.click(screen.getByRole("button", { name: "显示底部面板" }));
    expect(screen.getByText("左栏内容")).toBeTruthy();
    expect(screen.getByText("右栏内容")).toBeTruthy();
    expect(screen.getByText("下栏内容")).toBeTruthy();
  });

  it("exposes accessible separators that resize with the keyboard", () => {
    const { container } = renderLayout();
    const workspace = container.querySelector(".resizable-workspace") as HTMLElement;
    const left = screen.getByRole("separator", { name: "调整左侧面板宽度" });
    const right = screen.getByRole("separator", { name: "调整右侧面板宽度" });
    fireEvent.click(screen.getByRole("button", { name: "显示底部面板" }));
    const bottom = screen.getByRole("separator", { name: "调整底部面板高度" });

    expect(left.getAttribute("aria-orientation")).toBe("vertical");
    expect(right.getAttribute("aria-orientation")).toBe("vertical");
    expect(bottom.getAttribute("aria-orientation")).toBe("horizontal");
    fireEvent.keyDown(left, { key: "ArrowRight" });
    fireEvent.keyDown(right, { key: "ArrowLeft" });
    fireEvent.keyDown(bottom, { key: "ArrowUp" });

    expect(workspace.style.getPropertyValue("--left-track")).toBe("288px");
    expect(workspace.style.getPropertyValue("--right-track")).toBe("388px");
    expect(workspace.style.getPropertyValue("--bottom-rows")).toContain("308px");
  });
  it("opens the bottom once per activity signal and respects a manual close", () => {
    const view = render(
      <ResizableWorkspaceLayout mode="engineering" activitySignal="" left={<span>左栏内容</span>} leftRail={<button>项目文件</button>} center={<span>中栏内容</span>} right={<span>右栏内容</span>} bottom={<span>下栏内容</span>} />,
    );
    expect(screen.queryByText("下栏内容")).toBeNull();
    view.rerender(<ResizableWorkspaceLayout mode="engineering" activitySignal="run-1" left={<span>左栏内容</span>} leftRail={<button>项目文件</button>} center={<span>中栏内容</span>} right={<span>右栏内容</span>} bottom={<span>下栏内容</span>} />);
    expect(screen.getByText("下栏内容")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "隐藏底部面板" }));
    view.rerender(<ResizableWorkspaceLayout mode="engineering" activitySignal="run-1" left={<span>左栏内容</span>} leftRail={<button>项目文件</button>} center={<span>中栏内容</span>} right={<span>右栏内容</span>} bottom={<span>下栏内容</span>} />);
    expect(screen.queryByText("下栏内容")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "隐藏左侧项目栏" }));
    expect(screen.getByRole("button", { name: "项目文件" })).toBeTruthy();
  });
  it("keeps the engineering title and collapse action in one flow header", () => {
    const { container } = renderLayout();
    const header = container.querySelector(".workspace-panel-header");
    expect(header).toBeTruthy();
    expect(header?.textContent).toContain("工程工作区");
    expect(header?.querySelector('[aria-label="隐藏左侧项目栏"]')).toBeTruthy();
  });

  it("shows one non-blocking completion glow for a new completion signal", async () => {
    const view = render(
      <ResizableWorkspaceLayout mode="engineering" completionSignal="" left={<span>左栏</span>} center={<span>中栏</span>} right={<span>右栏</span>} bottom={<span>下栏</span>} />,
    );
    view.rerender(<ResizableWorkspaceLayout mode="engineering" completionSignal="run-completed-1" left={<span>左栏</span>} center={<span>中栏</span>} right={<span>右栏</span>} bottom={<span>下栏</span>} />);
    await waitFor(() => expect(view.container.querySelectorAll(".workspace-completion-glow")).toHaveLength(1));
    expect((view.container.querySelector(".workspace-completion-glow") as HTMLElement).getAttribute("aria-hidden")).toBe("true");
  });
});

function withinElement(element: Element) {
  return {
    querySelector: (selector: string) => element.querySelector(selector),
  };
}