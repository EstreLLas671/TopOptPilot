// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsWorkspace from "./SettingsWorkspace";
import type { AppSettings } from "./types";

const apiMocks = vi.hoisted(() => ({
  setAgentKey: vi.fn(),
  deleteAgentKey: vi.fn(),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  testAgent: vi.fn(),
  restartPi: vi.fn(),
  restartMatlab: vi.fn(),
  diagnostics: vi.fn(),
  clearCache: vi.fn(),
}));

vi.mock("./api", () => ({ api: apiMocks }));

const settings: AppSettings = {
  locale: "zh-CN", ui_density: "standard", startup_behavior: "research_list",
  theme: "light", custom_theme: { accent: "#3478e5", background: "#ffffff", surface: "#ffffff", text: "#222222" },
  api_key_status: "not_configured",
  agent: { model: "qwen3.7-plus", base_url: "https://example.test/v1", timeout_seconds: 30, max_retries: 1, safe_mode: true },
  compute: { matlab_root: null, python_workers: 1, matlab_timeout_seconds: 120, matlab_retry_count: 0 },
  new_research: { mode: "guided", budget_total: 4, budgets: {}, constraints: {}, material: {}, experiment: {} },
  data: {},
};

describe("SettingsWorkspace Agent credential controls", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.setAgentKey.mockResolvedValue({ configured: true, source: "credential_manager" });
    apiMocks.deleteAgentKey.mockResolvedValue({ deleted: true, source: "not_configured" });
    apiMocks.settings.mockResolvedValue({ ...settings, api_key_status: "credential_manager" });
    apiMocks.saveSettings.mockImplementation(async value => value);
    apiMocks.testAgent.mockResolvedValue({ ok: true, status: "verified", model: "qwen3.7-plus" });
  });

  it("saves and removes the API key through dedicated credential endpoints", async () => {
    const onSaved = vi.fn();
    render(<SettingsWorkspace settings={settings} onClose={vi.fn()} onSaved={onSaved}/>);
    await userEvent.click(screen.getByRole("button", { name: "Agent 与模型" }));

    const key = screen.getByLabelText("API Key");
    await userEvent.type(key, "secret-value");
    await userEvent.click(screen.getByRole("button", { name: "安全保存密钥" }));

    expect(apiMocks.setAgentKey).toHaveBeenCalledWith("secret-value");
    expect((key as HTMLInputElement).value).toBe("");
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({ api_key_status: "credential_manager" }));

    await userEvent.click(screen.getByRole("button", { name: "删除已保存密钥" }));
    expect(apiMocks.deleteAgentKey).toHaveBeenCalledOnce();
  });

  it("applies general settings only through the local Apply button", async () => {
    render(<SettingsWorkspace settings={settings} onClose={vi.fn()} onSaved={vi.fn()}/>);
    await userEvent.selectOptions(screen.getByLabelText("主题"), "dark");
    await userEvent.selectOptions(screen.getByLabelText("界面密度"), "compact");
    expect(apiMocks.saveSettings).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "应用" }));
    expect(apiMocks.saveSettings).toHaveBeenCalledWith(expect.objectContaining({ theme: "dark", ui_density: "compact" }));
  });

  it("keeps unapplied general drafts out of the top save and scopes connection output to Agent", async () => {
    render(<SettingsWorkspace settings={settings} onClose={vi.fn()} onSaved={vi.fn()}/>);
    await userEvent.selectOptions(screen.getByLabelText("主题"), "dark");
    await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
    expect(apiMocks.saveSettings).toHaveBeenLastCalledWith(expect.objectContaining({ theme: "light" }));
    await userEvent.click(screen.getByRole("button", { name: "Agent 与模型" }));
    await userEvent.click(screen.getByRole("button", { name: "测试连接" }));
    expect(await screen.findByText('{"ok":true,"status":"verified","model":"qwen3.7-plus"}')).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "通用与主题" }));
    expect(screen.queryByText('{"ok":true,"status":"verified","model":"qwen3.7-plus"}')).toBeNull();
  });
});
