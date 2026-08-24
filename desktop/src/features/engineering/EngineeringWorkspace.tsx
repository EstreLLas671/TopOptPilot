import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ChevronRight, FileCode2, FlaskConical, FolderOpen, Gauge, Pencil, Plus, Save, Search, Send, Settings2, SquareTerminal, Wrench } from "lucide-react";
import { api } from "../../api";
import type { EngineeringRun, PatchApproval, PatchProposal, ProjectEntry, ProjectFile, Research } from "../../types";
import { solverLaneLabel } from "../../workspace";
import { acceptGeneratedPatch, acceptPatchApply, acceptPatchPreview, advancePatchPreviewContext, approvalTokenFor, assistantConsentAfterAttempt, buildEngineeringAssistantRequest, buildEngineeringRunRequest, bundledRuntimeProfile, claimPatchApplyFlight, selectDetectedEnvironment, type EngineeringSolverLane, type MatlabInstallation, type PatchPreviewContext, type RuntimeInstallation } from "../../engineering-workspace";
import { mergeTerminalResults } from "./artifact-viewer";
import ResultViewer from "./ResultViewer";
import ResizableWorkspaceLayout from "../../components/ResizableWorkspaceLayout";
import ProjectTree from "../../components/ProjectTree";
import EngineeringIterationView from "./EngineeringIterationView";
import EngineeringComparisonView from "./EngineeringComparisonView";
import EngineeringBottomPanel, { EngineeringRunButton } from "./EngineeringBottomPanel";

const MonacoEditor = lazy(() => import("../../components/MonacoCodeEditor"));
type EngineeringHealth = { status: string; service: string; version: string; capabilities: { localMatlab: string; compiledRuntime: string } };
type Props = {
  health: EngineeringHealth | null;
  onError: (message: string) => void;
  onResearchBaseline: (run: EngineeringRun) => Promise<void>;
  researches?: Research[];
  selectedResearch?: Research | null;
  onCreateResearch?: () => void;
  onSelectResearch?: (id: string) => void | Promise<void>;
};
type ViewTab = "code" | "results" | "iteration" | "compare";

const languageFor = (path = "") => path.endsWith(".m") ? "matlab" : path.endsWith(".json") ? "json" : path.endsWith(".md") ? "markdown" : "plaintext";

export default function EngineeringWorkspace({
  health,
  onError,
  onResearchBaseline,
  researches = [],
  selectedResearch = null,
  onCreateResearch,
  onSelectResearch,
}: Props) {
  const [researchMenuOpen, setResearchMenuOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [projectRoot, setProjectRoot] = useState("");
  const [projectId, setProjectId] = useState("");
  const [files, setFiles] = useState<ProjectEntry[]>([]);
  const [selectedFile, setSelectedFile] = useState<ProjectFile | null>(null);
  const [dirty, setDirty] = useState(false);
  const [projectBusy, setProjectBusy] = useState(false);
  const [viewTab, setViewTab] = useState<ViewTab>("code");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [patchDiff, setPatchDiff] = useState("");
  const [patchApproval, setPatchApproval] = useState<PatchApproval | null>(null);
  const [assistantStatus, setAssistantStatus] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantConsent, setAssistantConsent] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [patchApplyBusy, setPatchApplyBusy] = useState(false);
  const [lane, setLane] = useState<EngineeringSolverLane>("python-fem");
  const [laneHealth, setLaneHealth] = useState(health);
  const [matlabExecutable, setMatlabExecutable] = useState("");
  const [matlabInstallation, setMatlabInstallation] = useState<MatlabInstallation | null>(null);
  const [matlabProbeState, setMatlabProbeState] = useState<"scanning" | "ready" | "failed" | "not-detected">("scanning");
  const [matlabDiagnostic, setMatlabDiagnostic] = useState("正在扫描本机 MATLAB…");
  const [runtimeProfileId, setRuntimeProfileId] = useState("");
  const [runtimeInstallation, setRuntimeInstallation] = useState<RuntimeInstallation | null>(null);
  const [runtimeState, setRuntimeState] = useState<"scanning" | "ready" | "detected-incompatible" | "not-detected" | "failed">("scanning");
  const [runtimeDiagnostic, setRuntimeDiagnostic] = useState("正在扫描本机 MATLAB Runtime…");
  const [environmentScanBusy, setEnvironmentScanBusy] = useState(false);
  const environmentScanGenerationRef = useRef(0);
  const [nelx, setNelx] = useState(30), [nely, setNely] = useState(15), [nelz, setNelz] = useState(4);
  const [volfrac, setVolfrac] = useState(0.4), [maxIter, setMaxIter] = useState(30);
  const [run, setRun] = useState<EngineeringRun | null>(null);
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [runBusy, setRunBusy] = useState(false);
  const [terminalSession, setTerminalSession] = useState("");
  const [terminalCommand, setTerminalCommand] = useState("");
  const [terminalOutput, setTerminalOutput] = useState<string[]>([]);
  const [terminalStatus, setTerminalStatus] = useState("未启动");
  const terminalSeen = useRef(new Set<number>());
  const [browserUrl, setBrowserUrl] = useState("http://127.0.0.1:5173");
  const [browserOpen, setBrowserOpen] = useState(false);
  const [baselineBusy, setBaselineBusy] = useState(false);
  const patchPreviewContextRef = useRef<PatchPreviewContext | null>(null);
  const generateNonceRef = useRef(0);
  const patchApplyBusyRef = useRef(false);
  patchPreviewContextRef.current = advancePatchPreviewContext(patchPreviewContextRef.current, {
    root: projectRoot,
    projectId,
    relativePath: selectedFile?.relative_path || "",
    fileDigest: selectedFile?.sha256 || "",
    unifiedDiff: patchDiff,
    dirty,
    assistantInstruction,
  });

  const reportError = useCallback((reason: unknown) => onError(String(reason)), [onError]);

  useEffect(() => setLaneHealth(health), [health]);
  useEffect(() => {
    const listener = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener("beforeunload", listener);
    return () => window.removeEventListener("beforeunload", listener);
  }, [dirty]);
  useEffect(() => {
    setAssistantConsent(false);
    setPatchDiff("");
    setPatchApproval(null);
    setAssistantStatus("");
  }, [projectRoot, projectId, selectedFile?.relative_path, selectedFile?.sha256]);

  const scanEngineeringEnvironment = useCallback(async () => {
    const generation = ++environmentScanGenerationRef.current;
    setEnvironmentScanBusy(true);
    setMatlabProbeState("scanning");
    setRuntimeState("scanning");
    try {
      const [matlabPayload, runtimePayload, bundledRuntime] = await Promise.all([
        api.engineeringInstallations(),
        api.engineeringRuntimeInstallations(),
        api.engineeringBundledRuntime(),
      ]);
      if (generation !== environmentScanGenerationRef.current) return;

      const selected = selectDetectedEnvironment(matlabPayload, runtimePayload);
      const selectedMatlab = matlabPayload.installations.find(
        item => item.executable === selected.matlabExecutable,
      ) || null;
      const selectedRuntime = runtimePayload.installations.find(
        item => item.profileId === selected.runtimeProfileId,
      ) || runtimePayload.installations[0] || null;
      const bundledProfileId = selected.runtimeProfileId ? null : bundledRuntimeProfile(bundledRuntime);
      const activeRuntimeProfile = selected.runtimeProfileId || bundledProfileId || "";

      setMatlabInstallation(selectedMatlab);
      setRuntimeInstallation(selectedRuntime);
      setRuntimeProfileId(activeRuntimeProfile);
      setRuntimeState(activeRuntimeProfile ? "ready" : selected.runtimeState);
      setRuntimeDiagnostic(
        activeRuntimeProfile && bundledProfileId
          ? bundledRuntime.diagnostic || "安装包内 Runtime 已就绪"
          : selected.runtimeDiagnostic,
      );
      setLaneHealth(previous => previous ? {
        ...previous,
        capabilities: {
          ...previous.capabilities,
          compiledRuntime: activeRuntimeProfile ? "ready" : selected.runtimeState,
        },
      } : previous);

      if (!selected.matlabExecutable) {
        setMatlabExecutable("");
        setMatlabProbeState("not-detected");
        setMatlabDiagnostic("未检测到可启动的 MATLAB。");
        return;
      }

      setMatlabDiagnostic(`正在验证 ${selected.matlabRelease || "MATLAB"}…`);
      const probe = await api.engineeringProbe(selected.matlabExecutable, selected.matlabRelease);
      if (generation !== environmentScanGenerationRef.current) return;
      setMatlabExecutable(probe.usable ? selected.matlabExecutable : "");
      setMatlabProbeState(probe.usable ? "ready" : "failed");
      setMatlabDiagnostic(probe.diagnostic || (probe.usable ? "MATLAB 已就绪" : "MATLAB 探测失败"));
      setLaneHealth(previous => previous ? {
        ...previous,
        capabilities: {
          ...previous.capabilities,
          localMatlab: probe.usable ? "ready" : "failed",
        },
      } : previous);
    } catch (reason) {
      if (generation !== environmentScanGenerationRef.current) return;
      setMatlabProbeState("failed");
      setRuntimeState("failed");
      setRuntimeProfileId("");
      reportError(reason);
    } finally {
      if (generation === environmentScanGenerationRef.current) setEnvironmentScanBusy(false);
    }
  }, [reportError]);

  useEffect(() => {
    void scanEngineeringEnvironment();
    return () => { environmentScanGenerationRef.current += 1; };
  }, [scanEngineeringEnvironment]);
  useEffect(() => {
    if (dirty) setPatchApproval(null);
  }, [dirty]);
  useEffect(() => {
    if (!terminalSession) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const value = await api.terminalPoll(terminalSession);
        if (cancelled) return;
        setTerminalStatus(value.status);
        setTerminalOutput(current => {
          const merged = mergeTerminalResults(current, terminalSeen.current, value.results);
          terminalSeen.current = merged.seenIds;
          return merged.lines;
        });
      } catch (reason) { if (!cancelled) setTerminalStatus(String(reason)); }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 650);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [terminalSession]);

  const visibleFiles = useMemo(() => query ? files.filter(file => file.relative_path.toLowerCase().includes(query.toLowerCase())) : files, [files, query]);

  async function refreshProject(root = projectRoot) {
    if (!root) return;
    setProjectBusy(true);
    try {
      const [opened, entries] = await Promise.all([api.projectOpen(root), api.projectList(root)]);
      setProjectId(opened.projectId); setFiles(entries); setProjectRoot(root);
    } catch (reason) { reportError(reason); }
    finally { setProjectBusy(false); }
  }
  async function openProject() {
    if (patchApplyBusy) return;
    if (dirty && !window.confirm("当前文件尚未保存，仍要切换项目吗？")) return;
    try {
      const root = await api.projectPickFolder();
      if (!root) return;
      setSelectedFile(null);
      setDirty(false);
      await refreshProject(root);
    } catch (reason) {
      reportError(reason);
    }
  }  async function searchProject() {
    if (!projectRoot || !query.trim()) return refreshProject();
    try { setFiles(await api.projectSearch(projectRoot, query.trim())); } catch (reason) { reportError(reason); }
  }
  async function openFile(entry: ProjectEntry) {
    if (patchApplyBusy) return;
    if (!projectRoot || entry.kind !== "file") return;
    if (dirty && !window.confirm("当前文件尚未保存，仍要打开另一个文件吗？")) return;
    setProjectBusy(true);
    try { setSelectedFile(await api.projectRead(projectRoot, entry.relative_path)); setDirty(false); setViewTab("code"); }
    catch (reason) { reportError(reason); }
    finally { setProjectBusy(false); }
  }
  async function saveFile() {
    if (patchApplyBusy) return;
    if (!projectRoot || !selectedFile || !dirty) return;
    setProjectBusy(true);
    try {
      const saved = await api.projectSave(projectRoot, selectedFile.relative_path, selectedFile.content, selectedFile.sha256);
      setSelectedFile(saved); setDirty(false);
    } catch (reason) { reportError(reason); }
    finally { setProjectBusy(false); }
  }
  async function createFile() {
    if (patchApplyBusy) return;
    if (!projectRoot) return openProject();
    const relative = window.prompt("新建文件相对路径（.m/.json/.md/.txt/.log/.csv）", "new_script.m");
    if (!relative?.trim()) return;
    try { const created = await api.projectCreate(projectRoot, relative.trim()); await refreshProject(); setSelectedFile(created); setDirty(false); setViewTab("code"); }
    catch (reason) { reportError(reason); }
  }
  async function renameFile() {
    if (patchApplyBusy) return;
    if (!projectRoot || !selectedFile || dirty) return;
    const target = window.prompt("新的相对路径", selectedFile.relative_path);
    if (!target?.trim() || target.trim() === selectedFile.relative_path) return;
    try { await api.projectRename(projectRoot, selectedFile.relative_path, target.trim()); await refreshProject(); setSelectedFile(await api.projectRead(projectRoot, target.trim())); }
    catch (reason) { reportError(reason); }
  }
  function proposal(): PatchProposal | null {
    if (!projectId || !selectedFile || !patchDiff.trim()) return null;
    return { projectId, baseDigest: selectedFile.sha256, files: [{ relativePath: selectedFile.relative_path, beforeDigest: selectedFile.sha256, unifiedDiff: patchDiff }] };
  }
  async function generatePatch() {
    if (patchApplyBusy) return;
    if (!projectId || !selectedFile || !assistantInstruction.trim()) return setAssistantStatus("请先保存并选择一个源文件，再输入修改要求。");
    const requestNonce = ++generateNonceRef.current;
    setAssistantBusy(true);
    try {
      const capturedContext = patchPreviewContextRef.current;
      if (!capturedContext) throw new Error("工程助手请求上下文不可用");
      const request = buildEngineeringAssistantRequest(projectId, selectedFile, assistantInstruction, assistantConsent);
      const generated = await api.engineeringPatch(request);
      const latestContext = patchPreviewContextRef.current;
      const accepted = latestContext
        ? acceptGeneratedPatch(generated, capturedContext, latestContext, requestNonce, generateNonceRef.current)
        : null;
      if (!accepted) {
        setAssistantStatus("生成期间项目、文件或指令已变化；旧结果已丢弃，请重新生成。");
        return;
      }
      const diff = accepted.files[0]?.unifiedDiff || "";
      if (!diff) throw new Error("工程助手没有返回可审阅差异");
      setPatchDiff(diff);
      setPatchApproval(null);
      setAssistantStatus("Qwen 已返回候选补丁；仍需校验差异并由你确认应用。");
    } catch (reason) {
      if (requestNonce === generateNonceRef.current) setAssistantStatus(String(reason));
    } finally {
      if (requestNonce === generateNonceRef.current) setAssistantBusy(false);
      setAssistantConsent(assistantConsentAfterAttempt());
    }
  }
  async function previewPatch() {
    if (patchApplyBusy) return;
    const value = proposal();
    const capturedContext = patchPreviewContextRef.current;
    if (!value || !capturedContext) return setAssistantStatus("请先打开文件并提供 unified diff。生成式助手未配置时不会伪造补丁。");
    setPatchApproval(null);
    try {
      const preview = await api.patchPreview(projectRoot, value);
      const latestContext = patchPreviewContextRef.current;
      const accepted = latestContext
        ? acceptPatchPreview(preview, capturedContext, latestContext)
        : null;
      if (!accepted) {
        setAssistantStatus("预览期间项目、文件或差异已变化；旧凭证已丢弃，请重新校验。");
        return;
      }
      setPatchApproval(accepted);
      setAssistantStatus("当前提案通过本次预览校验并取得一次性凭证；凭证不证明操作者身份。");
    }
    catch (reason) { setAssistantStatus(String(reason)); }
  }
  async function applyPatch() {
    if (!claimPatchApplyFlight(patchApplyBusyRef)) return;
    setPatchApplyBusy(true);
    try {
      const value = proposal();
      const approvalToken = approvalTokenFor(patchApproval, projectRoot, value);
      const capturedContext = patchPreviewContextRef.current;
      if (!value || !projectRoot || !approvalToken || dirty || !capturedContext) return;
      setPatchApproval(null);
      const applied = await api.patchApply(projectRoot, value, approvalToken);
      const latestContext = patchPreviewContextRef.current;
      const accepted = latestContext ? acceptPatchApply(applied, capturedContext, latestContext) : null;
      if (!accepted) {
        setAssistantStatus("应用期间项目或文件状态已变化；未覆盖当前编辑器，请刷新项目。");
        return;
      }
      setSelectedFile(accepted[0]);
      setPatchDiff("");
      setAssistantStatus("补丁已应用，基线摘要已刷新。");
      await refreshProject();
    }
    catch (reason) { setAssistantStatus(String(reason)); }
    finally {
      patchApplyBusyRef.current = false;
      setPatchApplyBusy(false);
    }
  }

  async function startRun() {
    setRunBusy(true); setEvents([]); setViewTab("results");
    try {
      if (lane !== "python-fem") await api.engineeringPreference(lane);
      const payload = buildEngineeringRunRequest(lane, projectId || "engineering-ui", runtimeProfileId);
      payload.task.geometry = { nelx, nely, nelz };
      payload.task.params = { max_iter: maxIter, volfrac };
      const created = await api.engineeringRun(payload);
      setRun(created);
      const socket = api.engineeringStream(created.runId, event => setEvents(items => [...items, event].slice(-80)));
      try {
        for (;;) {
          await new Promise(resolve => window.setTimeout(resolve, 250));
          const current = await api.engineeringRunGet(created.runId);
          setRun(current);
          if (["completed", "failed", "cancelled"].includes(current.status)) break;
        }
        const history = await api.engineeringEvents(created.runId);
        setEvents(history.events.slice(-80));
      } finally { socket.close(); }
    } catch (reason) { reportError(reason); }
    finally { setRunBusy(false); }
  }
  async function cancelRun() { if (run && !["completed", "failed", "cancelled"].includes(run.status)) setRun(await api.engineeringCancel(run.runId)); }
  async function exportReport() { if (!run) return; try { const ref = await api.engineeringReport(run.runId); window.alert(`报告已生成：${ref.relativePath}\nSHA-256: ${ref.sha256}`); setRun(await api.engineeringRunGet(run.runId)); } catch (reason) { reportError(reason); } }
  async function createResearchBaseline() {
    if (!run) return;
    setBaselineBusy(true);
    try { await onResearchBaseline(run); }
    catch (reason) { reportError(reason); }
    finally { setBaselineBusy(false); }
  }
  async function startTerminal() {
    if (!projectRoot) return reportError("请先打开工程项目，MATLAB 终端必须绑定受控根目录。");
    try {
      let executable = matlabExecutable;
      if (!executable) {
        const found = await api.engineeringInstallations(); executable = found.installations.find(item => item.executable)?.executable || "";
      }
      if (!executable) throw new Error("未发现可启动的 MATLAB 可执行文件。");
      const session = await api.terminalStart({ projectRoot, executable });
      terminalSeen.current = new Set(); setTerminalOutput([]); setTerminalSession(session.sessionId); setTerminalStatus(session.status);
    } catch (reason) { reportError(reason); }
  }
  async function sendTerminalCommand() {
    if (!terminalSession || !terminalCommand.trim()) return;
    const command = terminalCommand.trim();
    try { await api.terminalCommand(terminalSession, command); setTerminalOutput(items => [...items, `> ${command}`]); setTerminalCommand(""); }
    catch (reason) { reportError(reason); }
  }
  async function stopTerminal() {
    if (!terminalSession) return;
    try { const stopped = await api.terminalStop(terminalSession); setTerminalStatus(stopped.status); setTerminalSession(""); }
    catch (reason) { reportError(reason); }
  }
  async function toggleBrowser() {
    try {
      if (browserOpen) { await api.webviewClose(); setBrowserOpen(false); }
      else { await api.webviewCreate(browserUrl); setBrowserOpen(true); }
    } catch (reason) { reportError(reason); }
  }
  async function navigateBrowser() { try { if (!browserOpen) return toggleBrowser(); await api.webviewNavigate(browserUrl); } catch (reason) { reportError(reason); } }

  return <ResizableWorkspaceLayout mode="engineering"
    left={<>
      <div className="v2-pane-title research-project-heading"><span>研究</span><div className="pane-actions research-create-wrap"><button aria-label="新建或打开研究项目" title="新建或打开研究项目" onClick={() => setResearchMenuOpen(value => !value)}><Plus size={16}/></button>{researchMenuOpen ? <div className="research-project-menu"><button onClick={() => { setResearchMenuOpen(false); onCreateResearch?.(); }}><FlaskConical size={13}/>创建 Research</button><button onClick={() => { setResearchMenuOpen(false); void openProject(); }}><FolderOpen size={13}/>打开项目文件夹</button></div> : null}</div></div>
      <section className="selected-research-card"><FlaskConical size={16}/><div><b>{selectedResearch?.name || "尚未选择 Research"}</b><small>{selectedResearch ? `${selectedResearch.id} · ${selectedResearch.status}` : "点击 + 创建或选择研究项目"}</small></div></section>
      {selectedResearch ? <section className="research-goal-summary"><span>研究目标</span><p>{selectedResearch.goal}</p></section> : null}
      {researches.length ? <div className="compact-research-list">{researches.slice(0, 4).map(item => <button className={selectedResearch?.id === item.id ? "active" : ""} key={item.id} onClick={() => void onSelectResearch?.(item.id)}><ChevronRight size={11}/><span>{item.name}</span><small>{item.budget_used}/{item.budget_total}</small></button>)}</div> : null}
      <div className="sidebar-section-heading"><span>项目文件</span><div className="pane-actions"><button title="打开项目" disabled={patchApplyBusy} onClick={() => void openProject()}><FolderOpen size={14}/></button><button title="刷新项目" disabled={!projectRoot || projectBusy || patchApplyBusy} onClick={() => void refreshProject()}><Activity size={14}/></button><button title="新建文件" disabled={patchApplyBusy} onClick={() => void createFile()}><FileCode2 size={14}/></button></div></div>
      <label className="v2-search"><Search size={14}/><input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void searchProject(); }} placeholder="搜索文件与文本"/></label>
      <div className="project-root-label" title={projectRoot}>{projectRoot || "未打开项目文件夹"}</div>
      <ProjectTree entries={visibleFiles} selected={selectedFile} disabled={patchApplyBusy} onOpen={entry => void openFile(entry)}/>
      <button className="v2-outline sidebar-patch-button" onClick={() => setAssistantOpen(value => !value)}><Wrench size={14}/>补丁审批<small>人工确认</small></button>
      {selectedResearch ? <div className="research-budget-summary"><span>预算</span><b>{selectedResearch.budget_used}/{selectedResearch.budget_total}</b><div><i style={{ width: `${Math.min(100, selectedResearch.budget_used / Math.max(1, selectedResearch.budget_total) * 100)}%` }}/></div></div> : null}
    </>}
    center={<section className="engineering-center-shell">
      <nav className="v2-tabs engineering-view-tabs" role="tablist" aria-label="工程中央视图">
        <button role="tab" aria-selected={viewTab === "code"} className={`tab ${viewTab === "code" ? "active" : ""}`} onClick={() => setViewTab("code")}><FileCode2 size={14}/>代码{dirty ? <i>●</i> : null}</button>
        <button role="tab" aria-selected={viewTab === "results"} className={`tab ${viewTab === "results" ? "active" : ""}`} onClick={() => setViewTab("results")}><Gauge size={14}/>结果</button>
        <button role="tab" aria-selected={viewTab === "iteration"} className={`tab ${viewTab === "iteration" ? "active" : ""}`} onClick={() => setViewTab("iteration")}><Activity size={14}/>迭代可视化</button>
        <button role="tab" aria-selected={viewTab === "compare"} className={`tab ${viewTab === "compare" ? "active" : ""}`} onClick={() => setViewTab("compare")}><Settings2 size={14}/>参数调整与对比</button>
        <div className="engineering-tab-actions"><span title={selectedFile?.relative_path}>{selectedFile?.relative_path || "未选择文件"}</span><button className="tab-action" onClick={() => void renameFile()} disabled={!selectedFile || dirty || patchApplyBusy}><Pencil size={13}/>重命名</button><button className="tab-action" onClick={() => void saveFile()} disabled={!dirty || projectBusy || patchApplyBusy}><Save size={13}/>保存</button></div>
        <EngineeringRunButton busy={runBusy} label={`运行 ${solverLaneLabel(lane)}`} onRun={() => void startRun()}/>
      </nav>
      <div className="engineering-view-content" role="tabpanel">
        {viewTab === "code" ? <div className="monaco-host"><Suspense fallback={<div className="editor-loading">正在加载 Monaco 编辑器…</div>}><MonacoEditor language={languageFor(selectedFile?.relative_path)} value={selectedFile?.content || "% 打开项目后选择 UTF-8 源文件"} onChange={value => { if (selectedFile && !patchApplyBusy) { setSelectedFile({ ...selectedFile, content: value || "" }); setDirty(true); } }} options={{ readOnly: !selectedFile || projectBusy || patchApplyBusy, minimap: { enabled: false }, fontSize: 12, lineHeight: 20, automaticLayout: true, scrollBeyondLastLine: false, wordWrap: "off" }} theme="vs"/></Suspense></div> : null}
        {viewTab === "results" ? <ResultViewer run={run} onError={reportError}/> : null}
        {viewTab === "iteration" ? <EngineeringIterationView run={run} events={events}/> : null}
        {viewTab === "compare" ? <EngineeringComparisonView current={{ lane, nelx, nely, nelz, volfrac, maxIter }} run={run}/> : null}
      </div>
      <div className="engineering-composer">
        <div className="assistant-identity"><Wrench size={13}/><span>工程助手 · 只生成 PatchProposal，应用前必须预览并确认</span></div>
        <div className="assistant-command-line"><input value={assistantInstruction} onChange={event => setAssistantInstruction(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { setAssistantOpen(true); void generatePatch(); } }} placeholder="询问 iDeskTop、生成代码补丁或输入命令…"/><button aria-label="发送给工程助手" disabled={assistantBusy || patchApplyBusy || !assistantInstruction.trim()} onClick={() => { setAssistantOpen(true); void generatePatch(); }}>{assistantBusy ? <Activity className="spin" size={14}/> : <Send size={14}/>}</button></div>
        {assistantStatus ? <small>{assistantStatus}</small> : null}
      </div>
    </section>}
    bottom={<EngineeringBottomPanel
      terminalSession={terminalSession}
      terminalStatus={terminalStatus}
      terminalCommand={terminalCommand}
      terminalOutput={terminalOutput}
      events={events}
      run={run}
      browserUrl={browserUrl}
      browserOpen={browserOpen}
      matlabDiagnostic={matlabDiagnostic}
      runtimeDiagnostic={runtimeDiagnostic}
      onTerminalCommandChange={setTerminalCommand}
      onBrowserUrlChange={setBrowserUrl}
      onStartTerminal={() => void startTerminal()}
      onStopTerminal={() => void stopTerminal()}
      onSendTerminalCommand={() => void sendTerminalCommand()}
      onToggleBrowser={() => void toggleBrowser()}
      onNavigateBrowser={() => void navigateBrowser()}
    />}
    right={<>
      <div className="v2-pane-title"><span>检查器</span><Settings2 size={14}/></div>
      <section className="inspector-card environment-card"><h4>工程求解链路</h4><label className="inspector-field">执行后端<select value={lane} disabled={environmentScanBusy} onChange={event => setLane(event.target.value as EngineeringSolverLane)}><option value="python-fem">Python FEM</option><option value="local-matlab">本机 MATLAB</option><option value="compiled-runtime">编译 Runtime（可选）</option></select></label><div className="lane-row environment-row"><span><i className="lane-dot blue"/>本机 MATLAB</span><b className={`status ${matlabProbeState === "ready" ? "status-success" : "neutral"}`}>{matlabProbeState === "ready" ? `${matlabInstallation?.release || "MATLAB"} · 已就绪` : matlabProbeState === "scanning" ? "扫描中" : matlabProbeState === "not-detected" ? "未检测到" : "不可用"}</b></div><small className="environment-path" title={matlabExecutable || matlabInstallation?.executable}>{matlabExecutable || matlabInstallation?.executable || matlabDiagnostic}</small><div className="lane-row environment-row"><span><i className="lane-dot purple"/>编译 Runtime（可选）</span><b className={`status ${runtimeState === "ready" ? "status-success" : "neutral"}`}>{runtimeState === "ready" ? `${runtimeInstallation?.release || "Runtime"} · 已就绪` : runtimeState === "scanning" ? "扫描中" : runtimeState === "detected-incompatible" ? `${runtimeInstallation?.release || "Runtime"} · 版本不兼容` : runtimeState === "not-detected" ? "未检测到" : "不可用"}</b></div><small className="environment-path" title={runtimeInstallation?.path}>{runtimeInstallation?.path || "未选择本机 Runtime"}</small><p className="environment-diagnostic">{runtimeDiagnostic}</p><div className="inspector-actions"><button className="outline-button environment-rescan" disabled={environmentScanBusy} onClick={() => void scanEngineeringEnvironment()}><SquareTerminal size={14}/>{environmentScanBusy ? "正在扫描…" : "重新扫描电脑"}</button></div></section>
      <section className="inspector-card"><h4>求解参数</h4><div className="parameter-grid"><label>nelx<input type="number" min="4" value={nelx} onChange={event => setNelx(Number(event.target.value))}/></label><label>nely<input type="number" min="2" value={nely} onChange={event => setNely(Number(event.target.value))}/></label><label>nelz<input type="number" min="1" value={nelz} onChange={event => setNelz(Number(event.target.value))}/></label><label>体积分数<input type="number" min="0.05" max="0.95" step="0.05" value={volfrac} onChange={event => setVolfrac(Number(event.target.value))}/></label><label>最大迭代<input type="number" min="1" max="2000" value={maxIter} onChange={event => setMaxIter(Number(event.target.value))}/></label></div><div className="run-actions">
        <button onClick={() => void cancelRun()} disabled={!runBusy}><SquareTerminal size={13}/>取消</button>
        <button onClick={() => void exportReport()} disabled={!run || runBusy}><FileCode2 size={13}/>导出报告</button>
        <button className="baseline-button" onClick={() => void createResearchBaseline()}
          disabled={baselineBusy || !run || run.status !== "completed" || run.provenance.resultKind !== "solver" || !run.files.length}>
          <FlaskConical size={13}/>{baselineBusy ? "创建中" : "科研基线"}
        </button>
      </div></section>
      <section className="inspector-card"><h4>工程助手 <span className="permission">engineering</span></h4><p>只能对已打开文件生成并应用受控 PatchProposal；基线摘要过期时拒绝写入。</p><button className="primary-button" onClick={() => setAssistantOpen(value => !value)}>{assistantOpen ? "关闭补丁面板" : "打开补丁面板"}</button></section>
      {assistantOpen ? <section className="inspector-card assistant-card">
        <h4>PatchProposal</h4>
        <p className="digest-line">{selectedFile?.sha256 || "未选择文件"}</p>
        <textarea className="assistant-instruction" value={assistantInstruction} disabled={patchApplyBusy} onChange={event => setAssistantInstruction(event.target.value)} placeholder="描述希望 Qwen 对当前已保存文件做出的修改" spellCheck={false}/>
        <label className="source-consent">
          <input type="checkbox" checked={assistantConsent} disabled={patchApplyBusy} onChange={event => setAssistantConsent(event.target.checked)}/>
          允许本次把当前文件内容发送给 DashScope/Qwen
        </label>
        <small className="privacy-note">仅发送当前受控文件、摘要和上述要求；API Key 只从环境变量读取。</small>
        <div className="assistant-actions">
          <button className="outline-button" disabled={assistantBusy || patchApplyBusy || dirty || !selectedFile || !assistantInstruction.trim() || !assistantConsent} onClick={() => void generatePatch()}>{assistantBusy ? "生成中…" : "由 Qwen 生成"}</button>
          <button className="outline-button" disabled={patchApplyBusy || !patchDiff.trim()} onClick={() => void previewPatch()}>校验差异</button>
          <button className="primary-button" disabled={!approvalTokenFor(patchApproval, projectRoot, proposal()) || dirty || patchApplyBusy} onClick={() => void applyPatch()}>{patchApplyBusy ? "应用中…" : "确认应用"}</button>
        </div>
        <textarea className="patch-diff" value={patchDiff} disabled={patchApplyBusy} onChange={event => { setPatchDiff(event.target.value); setPatchApproval(null); }} placeholder="候选 unified diff；也可人工粘贴" spellCheck={false}/>
        {assistantStatus ? <small className="assistant-status">{assistantStatus}</small> : null}
      </section> : null}
      {run?.error ? <section className="inspector-card error-card"><h4>运行错误</h4><p>{run.error.code}: {run.error.message}</p></section> : null}
    </>}
  />;
}
