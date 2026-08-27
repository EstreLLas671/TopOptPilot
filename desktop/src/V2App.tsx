import { useCallback, useEffect, useMemo, useState } from "react";
import { Boxes, LoaderCircle, Settings2, ShieldCheck } from "lucide-react";
import { api, initializeBackend } from "./api";
import EngineeringWorkspace from "./features/engineering/EngineeringWorkspace";
import ResearchWorkspace from "./features/research/ResearchWorkspace";
import SettingsWorkspace from "./SettingsWorkspace";
import type { AppSettings, EngineeringEnvironment, EngineeringRun, Experiment, Research } from "./types";
import type { WorkspaceMode } from "./workspace";
import { workspaceLabel } from "./workspace";
import { applyTheme } from "./theme";
import { buildResearchBaselineRequest } from "./engineering-workspace";
import "./v2.css";
import "./v2-enhancements.css";

type EngineeringHealth = { status: string; service: string; version: string; capabilities: { localMatlab: string; compiledRuntime: string } };

export default function V2App() {
  const [mode, setMode] = useState<WorkspaceMode>("engineering");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState<EngineeringHealth | null>(null);
  const [environment, setEnvironment] = useState<EngineeringEnvironment | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [researches, setResearches] = useState<Research[]>([]);
  const [selectedResearch, setSelectedResearch] = useState<Research | null>(null);
  const [selectedExperiment, setSelectedExperiment] = useState<Experiment | null>(null);
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);

  const reportError = useCallback((message: string) => setError(message), []);
  const refreshSelected = useCallback(async (id: string) => {
    try {
      const value = await api.getResearch(id);
      setSelectedResearch(value);
      setResearches(items => items.map(item => item.id === value.id ? value : item));
    } catch (reason) { reportError(String(reason)); }
  }, [reportError]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        await initializeBackend();
        const [engineering, appSettings, researchList, detectedEnvironment] = await Promise.all([api.engineeringHealth(), api.settings(), api.listResearch(), api.engineeringEnvironment()]);
        if (cancelled) return;
        setHealth(engineering); setEnvironment(detectedEnvironment); setSettings(appSettings); setResearches(researchList);
        document.documentElement.lang = appSettings.locale;
        document.documentElement.dataset.density = appSettings.ui_density;
        applyTheme(appSettings);
        if (researchList[0]) setSelectedResearch(await api.getResearch(researchList[0].id));
        if (!cancelled) setReady(true);
      } catch (reason) { if (!cancelled) setError(String(reason)); }
    }
    void bootstrap();
    return () => { cancelled = true; };
  }, []);

  const refreshEnvironment = useCallback(async () => {
    const value = await api.engineeringEnvironmentRefresh();
    setEnvironment(value);
    setHealth(previous => previous ? { ...previous, capabilities: { ...previous.capabilities, localMatlab: value.matlab.probeState, compiledRuntime: value.runtime.state } } : previous);
    return value;
  }, []);

  const experiments = selectedResearch?.experiments ?? [];
  const active = selectedExperiment ?? selectedResearch?.best_experiment ?? experiments.at(-1);
  const safeMode = settings?.agent.safe_mode ?? true;

  const createResearchFromRun = useCallback(async (run: EngineeringRun) => {
    const name = window.prompt("请输入科研基线名称", "工程基线 · " + run.runId);
    if (!name?.trim()) return;
    const payload = { ...buildResearchBaselineRequest(run, settings?.new_research.budget_total ?? 12), name: name.trim() };
    const created = await api.researchFromEngineeringRun(run.runId, payload);
    setResearches(items => [created, ...items.filter(item => item.id !== created.id)]);
    setSelectedResearch(created);
    setSelectedExperiment(null);
    setMode("research");
  }, [settings?.new_research.budget_total]);

  async function createResearch() {
    try {
      const defaults = settings?.new_research;
      const created = await api.createResearch({ name: "新拓扑研究", goal: "验证工程基线与科研策略的差异", budget_total: defaults?.budget_total ?? 12, mode: defaults?.mode ?? "COPILOT", constraints: defaults?.constraints ?? {} });
      setResearches(items => [created, ...items]); setSelectedResearch(created); setSelectedExperiment(null); setMode("research");
    } catch (reason) { reportError(String(reason)); }
  }
  async function runResearchCommand(message = command) {
    const text = message.trim();
    if (!selectedResearch || !text) return;
    setBusy(true);
    try {
      const result = await api.command(selectedResearch.id, text, active?.id);
      setCommand("");
      await refreshSelected(selectedResearch.id);
      return result;
    } catch (reason) {
      reportError(String(reason));
      throw reason;
    } finally { setBusy(false); }
  }
  async function decide(id: string, action: "approve" | "reject") {
    try { action === "approve" ? await api.approve(id) : await api.reject(id); if (selectedResearch) await refreshSelected(selectedResearch.id); }
    catch (reason) { reportError(String(reason)); }
  }

  async function archiveResearch(id: string) {
    try {
      await api.archiveResearch(id);
      const remaining = researches.filter(item => item.id !== id);
      setResearches(remaining);
      if (selectedResearch?.id === id) {
        setSelectedExperiment(null);
        setSelectedResearch(remaining[0] ? await api.getResearch(remaining[0].id) : null);
      }
    } catch (reason) { reportError(String(reason)); }
  }
  async function restoreResearch(id: string) {
    try {
      const restored = await api.restoreResearch(id);
      setResearches(items => [restored, ...items.filter(item => item.id !== restored.id)]);
    } catch (reason) { reportError(String(reason)); }
  }
  const workspace = useMemo(() => mode === "engineering"
    ? <EngineeringWorkspace health={health} environment={environment} onRefreshEnvironment={refreshEnvironment} onError={reportError} onResearchBaseline={createResearchFromRun} researches={researches} selectedResearch={selectedResearch} onCreateResearch={createResearch} onSelectResearch={refreshSelected}/>
    : <ResearchWorkspace researches={researches} selected={selectedResearch} active={active} command={command} busy={busy} safeMode={safeMode} onCommand={runResearchCommand} onCreateResearch={createResearch} onArchive={archiveResearch} onRestore={restoreResearch} onDecision={decide} onError={reportError} onSelect={refreshSelected} onSelectExperiment={setSelectedExperiment} setCommand={setCommand}/>,
    [mode, health, reportError, createResearchFromRun, researches, selectedResearch, active, command, busy, safeMode, refreshSelected]);

  if (!ready) return <div className="v2-boot"><LoaderCircle className="spin" size={28}/><b>正在启动 TopOptPilot</b><span>{error || "连接统一 sidecar…"}</span></div>;
  if (settingsOpen && settings) return <SettingsWorkspace settings={settings} onClose={() => setSettingsOpen(false)} onSaved={value => { setSettings(value); document.documentElement.lang = value.locale; document.documentElement.dataset.density = value.ui_density; }}/>
  return <div className="v2-shell">
    <header className="v2-titlebar" data-tauri-drag-region>
      <div className="v2-brand"><span className="v2-brand-mark"><Boxes size={18}/></span><div><b>TopOptPilot</b><small>TOPOLOGY WORKBENCH</small></div></div>
      <nav className="v2-workspaces" aria-label="工作区">{(["engineering", "research"] as WorkspaceMode[]).map(item => <button key={item} title={item === "engineering" ? "工程开发" : "AI 科研"} className={mode === item ? "active" : ""} onClick={() => setMode(item)}><span className="workspace-dot" data-mode={item}/>{workspaceLabel(item)}</button>)}</nav>
      <div className="v2-actions"><span className="connection"><i/>SIDECAR {health?.version || ""}</span><button title="设置" aria-label="打开设置" onClick={() => setSettingsOpen(true)}><Settings2 size={16}/></button></div>
    </header>
    {error ? <div className="v2-error"><ShieldCheck size={15}/>{error}<button aria-label="关闭错误" onClick={() => setError("")}>×</button></div> : null}
    {workspace}
  </div>;
}
