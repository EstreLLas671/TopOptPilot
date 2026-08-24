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
    apiMocks.projectList.mockResolvedValue([]);
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

  it("scans MATLAB and Runtime at startup and shows an incompatible Runtime", async () => {
    apiMocks.engineeringInstallations.mockResolvedValue({
      preference: "local-matlab",
      installations: [{
        release: "R2024b",
        version: "24.2",
        executable: "D:/MATLAB/R2024b/bin/matlab.exe",
        source: "registry",
        probeState: "unknown",
      }],
    });
    apiMocks.engineeringRuntimeInstallations.mockResolvedValue({
      usable: true,
      runReady: false,
      installations: [{
        release: "R2025b",
        version: "25.2",
        path: "C:/Runtime/R2025b",
        source: "registry",
        usable: true,
        reason: "安装完整",
        runReady: false,
        runReason: "已编译求解器要求 R2024b",
        profileId: null,
        solverExecutable: null,
      }],
    });

    render(
      <EngineeringWorkspace
        health={null}
        onError={() => undefined}
        onResearchBaseline={async () => undefined}
      />,
    );

    await waitFor(() => {
      expect(apiMocks.engineeringInstallations).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringRuntimeInstallations).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringBundledRuntime).toHaveBeenCalledTimes(1);
      expect(apiMocks.engineeringProbe).toHaveBeenCalledWith(
        "D:/MATLAB/R2024b/bin/matlab.exe",
        "R2024b",
      );
    });
    expect(await screen.findByText("R2024b · 已就绪")).toBeTruthy();
    expect(screen.getByText(/已编译求解器要求 R2024b/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "重新扫描电脑" }));
    await waitFor(() => {
      expect(apiMocks.engineeringInstallations).toHaveBeenCalledTimes(2);
      expect(apiMocks.engineeringRuntimeInstallations).toHaveBeenCalledTimes(2);
      expect(apiMocks.engineeringBundledRuntime).toHaveBeenCalledTimes(2);
    });
  });

  it("renders the confirmed four-pane tabs, center assistant, and independent bottom tabs", async () => {
    render(
      <EngineeringWorkspace
        health={null}
        onError={() => undefined}
        onResearchBaseline={async () => undefined}
      />,
    );

    expect(screen.getByText("研究")).toBeTruthy();
    expect(screen.getByRole("button", { name: "新建或打开研究项目" })).toBeTruthy();
    expect(screen.getByRole("tree", { name: "项目文件树" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "新建或打开研究项目" }));
    await userEvent.click(screen.getByRole("button", { name: "打开项目文件夹" }));
    await waitFor(() => {
      expect(apiMocks.projectPickFolder).toHaveBeenCalledTimes(1);
      expect(apiMocks.projectOpen).toHaveBeenCalledWith("D:/Projects/cantilever");
      expect(apiMocks.projectList).toHaveBeenCalledWith("D:/Projects/cantilever");
    });
    expect(screen.getByRole("tab", { name: "代码" })).toBeTruthy();
    expect(screen.getByRole("tab", { name: "结果" })).toBeTruthy();
    const iterationTab = screen.getByRole("tab", { name: "迭代可视化" });
    const compareTab = screen.getByRole("tab", { name: "参数调整与对比" });
    expect(screen.getByPlaceholderText("询问 iDeskTop、生成代码补丁或输入命令…")).toBeTruthy();

    await userEvent.click(iterationTab);
    expect(screen.getByText("迭代时间轴")).toBeTruthy();
    await userEvent.click(compareTab);
    expect(screen.getByText("手动参数方案对比")).toBeTruthy();

    for (const name of ["MATLAB 终端", "运行日志", "输出", "工具调用", "制品", "诊断", "受限浏览器"]) {
      expect(screen.getByRole("tab", { name })).toBeTruthy();
    }
    await userEvent.click(screen.getByRole("tab", { name: "制品" }));
    expect(screen.getByText("本次运行制品")).toBeTruthy();
  });});