import { useState } from "react";
import { ArrowLeft, Database, Gauge, Globe2, KeyRound, LoaderCircle, RefreshCw, Save, ShieldCheck, Terminal, Trash2, Wifi } from "lucide-react";
import { api } from "./api";
import { applyTheme } from "./theme";
import type { AppSettings, SettingsDiagnostics } from "./types";
import "./settings.css";

type Props = { settings: AppSettings; onClose: () => void; onSaved: (value: AppSettings) => void };
const bytes = (value?: number) => value === undefined ? "—" : `${(value / 1024 / 1024).toFixed(1)} MB`;

function mergeGeneral(base: AppSettings, general: AppSettings): AppSettings {
  return {
    ...base,
    locale: general.locale,
    ui_density: general.ui_density,
    theme: general.theme,
    startup_behavior: general.startup_behavior,
    custom_theme: structuredClone(general.custom_theme),
  };
}

export default function SettingsWorkspace({ settings, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState(() => structuredClone(settings));
  const [persisted, setPersisted] = useState(() => structuredClone(settings));
  const [tab, setTab] = useState("general");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [notices, setNotices] = useState<Record<string, string>>({});
  const [agentTestNotice, setAgentTestNotice] = useState("");
  const [diagnostics, setDiagnostics] = useState<SettingsDiagnostics | null>(null);
  const zh = persisted.locale === "zh-CN";
  const label = (cn: string, en: string) => zh ? cn : en;
  const setSectionNotice = (section: string, value: string) => setNotices(current => ({ ...current, [section]: value }));

  function update(path: string, value: unknown) {
    setDraft(current => {
      const next = structuredClone(current) as unknown as Record<string, unknown>;
      const parts = path.split(".");
      let cursor = next;
      for (const key of parts.slice(0, -1)) cursor = cursor[key] as Record<string, unknown>;
      cursor[parts.at(-1)!] = value;
      return next as unknown as AppSettings;
    });
  }

  async function save() {
    setBusy(true);
    const pendingGeneral = structuredClone(draft);
    try {
      const value = await api.saveSettings(mergeGeneral(draft, persisted));
      setPersisted(value);
      setDraft(mergeGeneral(value, pendingGeneral));
      onSaved(value);
      setSectionNotice(tab, label("已保存。未点击“应用”的通用设置没有提交。", "Saved. Unapplied general settings were not submitted."));
    } catch (reason) {
      setSectionNotice(tab, String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function applyGeneral() {
    setBusy(true);
    try {
      const value = await api.saveSettings(mergeGeneral(persisted, draft));
      setPersisted(value);
      setDraft(current => mergeGeneral(current, value));
      onSaved(value);
      applyTheme(value);
      setSectionNotice("general", label("通用设置已应用并保存。", "General settings applied and saved."));
    } catch (reason) {
      setSectionNotice("general", String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function action(kind: "agent" | "pi" | "matlab" | "diagnostics" | "cache") {
    setBusy(true);
    try {
      const result = kind === "agent" ? await api.testAgent()
        : kind === "pi" ? await api.restartPi()
          : kind === "matlab" ? await api.restartMatlab()
            : kind === "diagnostics" ? await api.diagnostics()
              : await api.clearCache();
      if (kind === "diagnostics") setDiagnostics(result as SettingsDiagnostics);
      const message = typeof result === "object" ? JSON.stringify(result) : String(result);
      if (kind === "agent") setAgentTestNotice(message);
      else setSectionNotice(kind === "pi" ? "agent" : kind === "matlab" ? "compute" : "data", message);
    } catch (reason) {
      const section = kind === "agent" || kind === "pi" ? "agent" : kind === "matlab" ? "compute" : "data";
      if (kind === "agent") setAgentTestNotice(String(reason));
      else setSectionNotice(section, String(reason));
    } finally {
      setBusy(false);
    }
  }

  const valueAt = (path: string) => path.split(".").reduce<unknown>((value, key) => (value as Record<string, unknown> | undefined)?.[key], draft);
  const field = (name: string, path: string, type = "text") => (
    <label className="settings-field">{name}
      <input type={type} value={String(valueAt(path) ?? "")} onChange={event => update(path, type === "number" ? Number(event.target.value) : event.target.value)}/>
    </label>
  );

  async function saveAgentKey() {
    setBusy(true);
    try {
      await api.setAgentKey(apiKey);
      setApiKey("");
      const fresh = await api.settings();
      setPersisted(fresh);
      setDraft(current => ({ ...current, api_key_status: fresh.api_key_status }));
      onSaved(fresh);
      setSectionNotice("agent", label("密钥已安全保存到 Windows 凭据管理器。请重启 Pi 会话。", "Key saved to Windows Credential Manager. Restart Pi sessions."));
    } catch (reason) {
      setSectionNotice("agent", String(reason));
    } finally {
      setBusy(false);
    }
  }

  async function removeAgentKey() {
    setBusy(true);
    try {
      await api.deleteAgentKey();
      const fresh = await api.settings();
      setPersisted(fresh);
      setDraft(current => ({ ...current, api_key_status: fresh.api_key_status }));
      onSaved(fresh);
      setSectionNotice("agent", label("已删除凭据管理器中的密钥。", "Credential Manager key deleted."));
    } catch (reason) {
      setSectionNotice("agent", String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <div className="settings-workspace">
    <header className="settings-title">
      <button onClick={onClose}><ArrowLeft/>{label("返回工作台", "Back to workspace")}</button>
      <div><b>TopOptPilot {label("设置中心", "Settings")}</b><small>{label("全局默认值只影响后续新建 Research", "Global defaults affect only future Research")}</small></div>
      <button className="approve" disabled={busy} onClick={() => void save()}>{busy ? <LoaderCircle className="spin"/> : <Save/>}{label("保存设置", "Save settings")}</button>
    </header>
    <aside className="settings-nav">
      {[
        ["general", <Globe2/>, label("通用与主题", "General & theme")],
        ["agent", <Terminal/>, label("Agent 与模型", "Agent & model")],
        ["compute", <Gauge/>, label("MATLAB 与计算", "MATLAB & compute")],
        ["defaults", <ShieldCheck/>, label("新研究默认值", "New research defaults")],
        ["data", <Database/>, label("数据与诊断", "Data & diagnostics")],
      ].map(([key, icon, text]) => <button key={key as string} className={tab === key ? "active" : ""} onClick={() => setTab(key as string)}>{icon}{text}</button>)}
    </aside>
    <main className="settings-content">
      {tab === "general" ? <section>
        <h1>通用与主题</h1>
        <div className="settings-grid">
          <label className="settings-field">默认语言<select value={draft.locale} onChange={event => update("locale", event.target.value)}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label>
          <label className="settings-field">界面密度<select value={draft.ui_density} onChange={event => update("ui_density", event.target.value)}><option value="compact">紧凑</option><option value="standard">标准</option><option value="comfortable">舒展</option></select></label>
          <label className="settings-field">主题<select value={draft.theme} onChange={event => update("theme", event.target.value)}><option value="light">浅色</option><option value="dark">完整暗色</option><option value="system">跟随系统</option><option value="custom">自定义语义色板</option></select></label>
          <label className="settings-field">启动行为<select value={draft.startup_behavior} onChange={event => update("startup_behavior", event.target.value)}><option value="resume_last">恢复上次研究</option><option value="research_list">打开研究列表</option></select></label>
        </div>
        {draft.theme === "custom" ? <div className="theme-token-grid">
          {field("强调色", "custom_theme.accent", "color")}{field("强调悬停色", "custom_theme.accent_hover", "color")}
          {field("页面背景", "custom_theme.background", "color")}{field("面板色", "custom_theme.surface", "color")}
          {field("浮层色", "custom_theme.elevated", "color")}{field("主文字", "custom_theme.text", "color")}
          {field("次文字", "custom_theme.muted_text", "color")}{field("边框色", "custom_theme.border", "color")}
          {field("成功色", "custom_theme.success", "color")}{field("警告色", "custom_theme.warning", "color")}
          {field("错误色", "custom_theme.danger", "color")}{field("图表主色", "custom_theme.chart", "color")}
          {field("图表网格", "custom_theme.chart_grid", "color")}{field("3D 画布背景", "custom_theme.volume_background", "color")}
          <label className="settings-field theme-contrast">界面对比度 <output>{draft.custom_theme.contrast ?? 100}%</output><input type="range" min="80" max="140" step="1" value={draft.custom_theme.contrast ?? 100} onChange={event => update("custom_theme.contrast", Number(event.target.value))}/></label>
        </div> : null}
        <button disabled={busy} onClick={() => void applyGeneral()}>应用</button>
        <p>点击“应用”后，通用选项才会保存并作用于当前窗口。</p>
        {notices.general ? <div className="settings-notice">{notices.general}</div> : null}
      </section> : null}
      {tab === "agent" ? <section>
        <h1>Agent 与模型</h1>
        <p>DashScope API Key：<b>{draft.api_key_status}</b>。密钥只存 Windows 凭据管理器，不进入 SQLite、日志、报告或复现包。</p>
        <div className="settings-grid">
          <label className="settings-field">API Key<input type="password" autoComplete="new-password" value={apiKey} onChange={event => setApiKey(event.target.value)}/></label>
          {field("默认模型", "agent.model")}{field("Base URL", "agent.base_url")}{field("请求超时（秒）", "agent.timeout_seconds", "number")}{field("自动重试次数", "agent.max_retries", "number")}
          <label className="settings-check"><input type="checkbox" checked={draft.agent.safe_mode} onChange={event => update("agent.safe_mode", event.target.checked)}/>启用 Safe Mode</label>
        </div>
        <div className="settings-action-grid">
          <button disabled={!apiKey || busy} onClick={() => void saveAgentKey()}><KeyRound/>安全保存密钥</button>
          <button disabled={busy} onClick={() => void removeAgentKey()}><Trash2/>删除已保存密钥</button>
          <button onClick={() => void action("agent")}><Wifi/>测试连接</button>
          <button onClick={() => void action("pi")}><RefreshCw/>重启所有 Pi 会话</button>
        </div>
        {agentTestNotice ? <div className="settings-notice settings-agent-test" aria-live="polite">{agentTestNotice}</div> : null}
        <p>Safe Mode 明确标记为规则回退，不代表在线模型决策。</p>
        {notices.agent ? <div className="settings-notice">{notices.agent}</div> : null}
      </section> : null}
      {tab === "compute" ? <section>
        <h1>MATLAB 与计算</h1>
        <div className="settings-grid">{field("MATLAB 根目录", "compute.matlab_root")}{field("Python FEM 并发数", "compute.python_workers", "number")}{field("MATLAB 默认超时（秒）", "compute.matlab_timeout_seconds", "number")}{field("MATLAB 自动重试次数", "compute.matlab_retry_count", "number")}</div>
        <button onClick={() => void action("matlab")}><RefreshCw/>重启受控 MATLAB MCP</button>
        <p className="warning">科研 F3 只允许真实 MATLAB MCP，不能启用 Python fallback。</p>
        {notices.compute ? <div className="settings-notice">{notices.compute}</div> : null}
      </section> : null}
      {tab === "defaults" ? <section>
        <h1>新研究默认值</h1>
        <p>不会修改任何已有 Research、实验、决策或复现包。</p>
        <div className="settings-grid">{field("默认模式", "new_research.mode")}{field("总预算", "new_research.budget_total", "number")}{field("F0 预算", "new_research.budgets.f0", "number")}{field("F1 预算", "new_research.budgets.f1", "number")}{field("F2 预算", "new_research.budgets.f2", "number")}{field("F3 预算", "new_research.budgets.f3", "number")}{field("材料 E", "new_research.material.E", "number")}{field("泊松比 nu", "new_research.material.nu", "number")}</div>
        {notices.defaults ? <div className="settings-notice">{notices.defaults}</div> : null}
      </section> : null}
      {tab === "data" ? <section>
        <h1>数据与诊断</h1>
        {field("下次启动使用的新数据目录", "data.next_data_dir")}
        <p>不会自动迁移旧数据；保存后重启应用生效。</p>
        {field(label("缓存目录（保存时迁移）", "Cache directory (migrates on save)"), "data.cache_dir")}
        <p>{label("填写一个已存在的可写目录后保存；现有缓存会立即迁移，失败时自动回滚。留空则迁回默认位置。", "Enter an existing writable directory and save; existing cache migrates immediately and rolls back on failure. Leave empty to return to the default location.")}</p>
        {draft.data.cache_migration ? <p>{label("最近一次迁移：", "Last migration: ")}{draft.data.cache_migration.moved_files}{label(" 个文件 → ", " file(s) → ")}{draft.data.cache_migration.cache_dir}</p> : null}
        <button onClick={() => void action("diagnostics")}>刷新只读诊断快照</button>
        <button onClick={() => void action("cache")}>清理可再生缓存</button>
        <p>清理不会删除 Research 记录或原始 MATLAB 证据。</p>
        {diagnostics ? <pre className="diagnostics">数据：{diagnostics.data_dir}{"\n"}数据库：{diagnostics.database}{"\n"}缓存目录：{diagnostics.cache_dir ?? "—"}{"\n"}缓存：{bytes(diagnostics.cache_bytes)} · 可用磁盘：{bytes(diagnostics.free_disk_bytes)}{"\n"}{JSON.stringify(diagnostics.health, null, 2)}</pre> : null}
        {notices.data ? <div className="settings-notice">{notices.data}</div> : null}
      </section> : null}
    </main>
  </div>;
}
