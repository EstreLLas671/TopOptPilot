// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  engineeringInstallations: vi.fn(),
  engineeringRuntimeInstallations: vi.fn(),
  engineeringBundledRuntime: vi.fn(),
  engineeringProbe: vi.fn(),
  projectPickFolder: vi.fn(),
  projectOpen: vi.fn(),
  projectList: vi.fn(),
  conversationList: vi.fn(),
  conversationCreate: vi.fn(),
  conversationMessages: vi.fn(),
  conversationMessage: vi.fn(),
  conversationDelete: vi.fn(),
  conversationAttachment: vi.fn(),
}));

vi.mock("./api", () => ({
  api: apiMocks,
}));

vi.mock("./components/MonacoCodeEditor", () => ({
  default: () => <div data-testid="monaco-editor" />,
}));

import EngineeringWorkspace from "./features/engineering/EngineeringWorkspace";

describe("EngineeringWorkspace mount", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    apiMocks.engineeringInstallations.mockResolvedValue({
      preference: "local-matlab",
      installations: [],
    });
    apiMocks.engineeringRuntimeInstallations.mockResolvedValue({
      usable: false,
      runReady: false,
      installations: [],
    });
    apiMocks.engineeringBundledRuntime.mockResolvedValue({
      state: "unavailable",
      usable: false,
      profileId: null,
      diagnostic: "standard package",
    });
    apiMocks.engineeringProbe.mockResolvedValue({
      usable: true,
      version: "24.2",
      diagnostic: "MATLAB R2024b 可用",
    });
    apiMocks.projectPickFolder.mockResolvedValue("D:/Projects/cantilever");
    apiMocks.projectOpen.mockResolvedValue({ root: "D:/Projects/cantilever", projectId: "project-1" });
    apiMocks.projectList.mockResolvedValue({ entries: [], truncated: false, skippedDirectories: 0 });
    apiMocks.conversationList.mockResolvedValue([]);
    apiMocks.conversationCreate.mockResolvedValue({
      id: "conversation-1", scope: "engineering", ownerId: "engineering-unbound",
      title: "工程对话", createdAt: "2026-08-26T00:00:00Z", updatedAt: "2026-08-26T00:00:00Z",
    });
    apiMocks.conversationMessages.mockResolvedValue([]);
  });

  it("mounts without violating the Rules of Hooks", () => {
    expect(() => render(
      <EngineeringWorkspace
        health={null}
        onError={() => undefined}
        onResearchBaseline={async () => undefined}
      />,
    )).not.toThrow();
  });

  it("explains when project discovery was bounded to keep the workspace responsive", async () => {
    apiMocks.projectList.mockResolvedValue({ entries: [], truncated: true, skippedDirectories: 2 });
    render(<EngineeringWorkspace health={null} onError={() => undefined} onResearchBaseline={async () => undefined}/>);

    await userEvent.click(screen.getByRole("button", { name: "新建或打开研究项目" }));

    expect(await screen.findByText(/已跳过 2 个依赖、构建或过深目录/)).toBeTruthy();
    expect(screen.getByText(/文件树最多检索 2,000 个支持文件/)).toBeTruthy();
  });

  it("scans MATLAB and Runtime once and exposes explicit refresh in the parameter dialog", async () => {
    apiMocks.engineeringInstallations.mockResolvedValue({
      preference: "local-matlab",
      installations: [{
        release: "R2024b", version: "24.2",
        executable: "D:/MATLAB/R2024b/bin/matlab.exe",
        source: "registry", probeState: "unknown",
      }],
    });
    apiMocks.engineeringRuntimeInstallations.mockResolvedValue({
      usable: true, runReady: false,
      installations: [{
        release: "R2025b", version: "25.2", path: "C:/Runtime/R2025b",
        source: "registry", usable: true, reason: "安装完整", runReady: false,
        runReason: "已编译求解器要求 R2024b", profileId: null, solverExecutable: null,
      }],
    });

    render(<EngineeringWorkspace health={null} onError={() => undefined} onResearchBaseline={async () => undefined}/>);
    await waitFor(() => {
      expect(apiMocks.engineeringInstallations).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringRuntimeInstallations).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringBundledRuntime).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringProbe).toHaveBeenCalledWith("D:/MATLAB/R2024b/bin/matlab.exe", "R2024b");
    });

    await userEvent.click(screen.getByRole("button", { name: "打开参数配置" }));
    expect(await screen.findByText("MATLAB R2024b 可用")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "重新检测 MATLAB" }));
    await waitFor(() => expect(apiMocks.engineeringInstallations).toHaveBeenCalledTimes(2));
  });

  it("offers explicit 2D and 3D parameter modes in the workspace-wide dialog", async () => {
    render(<EngineeringWorkspace health={null} onError={() => undefined} onResearchBaseline={async () => undefined}/>);
    await userEvent.click(screen.getByRole("button", { name: "打开参数配置" }));
    const dimension = screen.getByLabelText("求解维度") as HTMLSelectElement;
    expect(dimension.value).toBe("3d");
    expect(screen.getByLabelText("Z 单元")).toBeTruthy();

    await userEvent.selectOptions(dimension, "2d");
    expect(dimension.value).toBe("2d");
    expect((screen.getByLabelText("Z 单元") as HTMLInputElement).value).toBe("2D 固定为 1");
  });

  it("keeps Engineering free of Research details and puts workspace left and settings right", async () => {
    const { container } = render(<EngineeringWorkspace health={null} onError={() => undefined} onResearchBaseline={async () => undefined}/>);

    const leftPanel = container.querySelector(".workspace-left");
    const rightPanel = container.querySelector(".workspace-right");
    expect(leftPanel?.textContent).toContain("工程工作区");
    expect(leftPanel?.querySelector('.workspace-panel-header [aria-label="隐藏左侧项目栏"]')).toBeTruthy();
    expect(leftPanel?.textContent).toContain("工作区");
    expect(leftPanel?.textContent).toContain("历史对话");
    expect(leftPanel?.textContent).toContain("项目文件");
    expect(leftPanel?.textContent).not.toContain("环境配置");
    expect(rightPanel?.textContent).toContain("环境与参数");
    expect(rightPanel?.textContent).toContain("环境配置");
    expect(rightPanel?.textContent).toContain("参数配置");
    expect(rightPanel?.textContent).not.toContain("历史对话");

    expect(screen.getByText("环境与参数")).toBeTruthy();
    expect(screen.getByRole("region", { name: "环境配置" })).toBeTruthy();
    const matlabBackend = screen.getByRole("button", { name: "MATLAB" });
    const pythonBackend = screen.getByRole("button", { name: "Python" });
    expect(matlabBackend.getAttribute("aria-pressed")).toBe("true");
    expect(pythonBackend.getAttribute("aria-pressed")).toBe("false");
    await userEvent.click(pythonBackend);
    expect(pythonBackend.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("region", { name: "参数配置" })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: "工程开发导航" })).toBeNull();
    expect(screen.queryByText("研究目标")).toBeNull();
    expect(screen.getByRole("tab", { name: "工作区" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "历史对话" })).toBeTruthy();
    expect(screen.getByRole("tree", { name: "项目文件树" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "新建或打开研究项目" }));
    await waitFor(() => {
      expect(apiMocks.projectPickFolder).toHaveBeenCalledTimes(1);
      expect(apiMocks.projectOpen).toHaveBeenCalledWith("D:/Projects/cantilever");
      expect(apiMocks.projectList).toHaveBeenCalledWith("D:/Projects/cantilever");
    });

    const chatTab = screen.getByRole("tab", { name: "聊天" });
    expect(chatTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("tab", { name: "代码" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "结果" })).toBeTruthy();
    const iterationTab = screen.getByRole("tab", { name: "迭代可视化" });
    const compareTab = screen.getByRole("tab", { name: "参数调整与对比" });
    expect(screen.getByPlaceholderText("询问当前工程、参数或结果…")).toBeTruthy();

    await userEvent.click(iterationTab);
    expect(screen.getByText("迭代时间轴")).toBeTruthy();
    await userEvent.click(compareTab);
    expect(screen.getByText("参数方案与真实结果")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "显示底部面板" }));
    for (const name of ["MATLAB 终端", "运行日志", "输出", "工具调用", "制品", "诊断"]) {
      expect(screen.getByRole("tab", { name })).toBeTruthy();
    }
    await userEvent.click(screen.getByRole("tab", { name: "制品" }));
    expect(screen.getByText("本次运行制品")).toBeTruthy();
  });
});
