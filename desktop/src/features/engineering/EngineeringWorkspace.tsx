import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ChevronRight, FileCode2, FlaskConical, FolderOpen, Gauge, MessageCircle, Pencil, Plus, Save, Search, Send, Settings2 } from "lucide-react";
import { api } from "../../api";
import type { Conversation, EngineeringRun, PatchApproval, PatchProposal, ProjectEntry, ProjectFile, Research } from "../../types";
import { solverLaneLabel } from "../../workspace";
import { acceptGeneratedPatch, acceptPatchApply, acceptPatchPreview, advancePatchPreviewContext, approvalTokenFor, assistantConsentAfterAttempt, buildEngineeringAssistantRequest, buildEngineeringRunRequest , claimPatchApplyFlight , type EngineeringSolverLane, type MatlabInstallation, type PatchPreviewContext, type RuntimeInstallation } from "../../engineering-workspace";
import { mergeTerminalResults } from "./artifact-viewer";
import ResultViewer from "./ResultViewer";
import ResizableWorkspaceLayout from "../../components/ResizableWorkspaceLayout";
import ProjectTree from "../../components/ProjectTree";
import EngineeringIterationView from "./EngineeringIterationView";
import EngineeringComparisonWorkspace from "./EngineeringComparisonWorkspace";
import EngineeringBottomPanel, { EngineeringRunButton } from "./EngineeringBottomPanel";
import EngineeringChatPanel from "./EngineeringChatPanel";
import ParameterConfigurationDialog from "./ParameterConfigurationDialog";
import { DEFAULT_OPTIMIZATION_CONFIG, engineeringTaskFromConfig, validateOptimizationConfig, type OptimizationConfig } from "../../optimization-config";

const MonacoEditor = lazy(() => import("../../components/MonacoCodeEditor"));
function relativeConversationTime(value: number, now: number): string {
  const timestamp = value < 1_000_000_000_000 ? value * 1000 : value;
  const delta = Math.max(0, now - timestamp);
  if (delta < 60_000) return "刚刚";
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)} 分钟前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)} 小时前`;
  if (delta < 7 * 86_400_000) return `${Math.floor(delta / 86_400_000)} 天前`;
  return new Date(timestamp).toLocaleDateString();
}
type EngineeringHealth = { status: string; service: string; version: string; capabilities: { localMatlab: string; compiledRuntime: string } };
type Props = {
  health: EngineeringHealth | null;
  environment?: import("../../types").EngineeringEnvironment | null;
  onRefreshEnvironment?: () => Promise<import("../../types").EngineeringEnvironment>;
  onError: (message: string) => void;
  onResearchBaseline: (run: EngineeringRun) => Promise<void>;
  researches?: Research[];
  selectedResearch?: Research | null;
  onCreateResearch?: () => void;
  onSelectResearch?: (id: string) => void | Promise<void>;
};
type ViewTab = "chat" | "code" | "results" | "iteration" | "compare";

const languageFor = (path = "") => path.endsWith(".m") ? "matlab" : path.endsWith(".json") ? "json" : path.endsWith(".md") ? "markdown" : "plaintext";

export default function EngineeringWorkspace({
  health,
  environment = null,
  onRefreshEnvironment,
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
  const [viewTab, setViewTab] = useState<ViewTab>("chat");
  const [rightTab, setRightTab] = useState<"workspace" | "history">("workspace");
  const [conversationHistory, setConversationHistory] = useState<Conversation[]>([]);
  const [clockNow, setClockNow] = useState(() => Date.now());
  useEffect(() => { const timer = window.setInterval(() => setClockNow(Date.now()), 30_000); return () => window.clearInterval(timer); }, []);
  const [activeConversationId, setActiveConversationId] = useState("");
  const [requestedConversationId, setRequestedConversationId] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [patchDiff, setPatchDiff] = useState("");
  const [patchApproval, setPatchApproval] = useState<PatchApproval | null>(null);
  const [assistantStatus, setAssistantStatus] = useState("");
  const [assistantInstruction, setAssistantInstruction] = useState("");
  const [assistantConsent, setAssistantConsent] = useState(false);
  const [assistantBusy, setAssistantBusy] = useState(false);
  const [patchApplyBusy, setPatchApplyBusy] = useState(false);
  const [lane, setLane] = useState<EngineeringSolverLane>("local-matlab");
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
  const engineeringWorkspaceRestoredRef = useRef(false);
  const [optimizationConfig, setOptimizationConfig] = useState<OptimizationConfig>(DEFAULT_OPTIMIZATION_CONFIG);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [run, setRun] = useState<EngineeringRun | null>(null);
  const nelx = optimizationConfig.nelx, nely = optimizationConfig.nely, nelz = optimizationConfig.nelz, volfrac = optimizationConfig.volfrac, maxIter = optimizationConfig.maxIterations;
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [runBusy, setRunBusy] = useState(false);
  const [completionSignal, setCompletionSignal] = useState("");
  const [bottomActivitySignal, setBottomActivitySignal] = useState("");
  const [terminalSession, setTerminalSession] = useState("");
  const [terminalCommand, setTerminalCommand] = useState("");
  const [terminalOutput, setTerminalOutput] = useState<string[]>([]);
  const [terminalStatus, setTerminalStatus] = useState("未启动");
  const terminalSeen = useRef(new Set<number>());
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
  const updateConfig = useCallback((patch: Partial<OptimizationConfig>) => setOptimizationConfig(current => ({ ...current, ...patch })), []);
  const configErrors = validateOptimizationConfig(optimizationConfig);
  const configVersionRef = useRef(JSON.stringify({ lane, optimizationConfig }));
  useEffect(() => {
    const version = JSON.stringify({ lane, optimizationConfig });
    if (configVersionRef.current !== version) {
      configVersionRef.current = version;
      setRun(null);
      setEvents([]);
    }
  }, [lane, optimizationConfig]);

  useEffect(() => {
    let cancelled = false;
    try {
      const raw = window.localStorage.getItem("idesktop:engineering-workspace-v2");
      if (raw) {
        const saved = JSON.parse(raw) as {
          projectRoot?: string; selectedPath?: string; viewTab?: ViewTab;
          lane?: EngineeringSolverLane; optimizationConfig?: OptimizationConfig;
        };
        if (saved.viewTab && ["chat", "code", "results", "iteration", "compare"].includes(saved.viewTab)) setViewTab(saved.viewTab);
        if (saved.lane && ["local-matlab", "compiled-runtime", "python-fem"].includes(saved.lane)) {
          setLane(saved.lane === "compiled-runtime" ? "local-matlab" : saved.lane);
        }
        if (saved.optimizationConfig && !validateOptimizationConfig(saved.optimizationConfig).length) setOptimizationConfig(saved.optimizationConfig);
        if (saved.projectRoot) {
          void api.projectOpen(saved.projectRoot).then(async opened => {
            const entries = await api.projectList(opened.root);
            if (cancelled) return;
            setProjectRoot(opened.root); setProjectId(opened.projectId); setFiles(entries);
            if (saved.selectedPath) {
              const file = await api.projectRead(opened.root, saved.selectedPath).catch(() => null);
              if (!cancelled && file) setSelectedFile(file);
            }
          }).catch(() => undefined);
        }
      }
    } catch { window.localStorage.removeItem("idesktop:engineering-workspace-v2"); }
    engineeringWorkspaceRestoredRef.current = true;
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!engineeringWorkspaceRestoredRef.current) return;
    window.localStorage.setItem("idesktop:engineering-workspace-v2", JSON.stringify({
      projectRoot, selectedPath: selectedFile?.relative_path || "", viewTab, lane, optimizationConfig,
    }));
  }, [projectRoot, selectedFile?.relative_path, viewTab, lane, optimizationConfig]);
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

  const applyEnvironment = useCallback((value: import("../../types").EngineeringEnvironment) => {
    const matlab = value.matlab;
    setMatlabExecutable(matlab.probeState === "ready" ? matlab.path : "");
    setMatlabInstallation(matlab.path ? { executable: matlab.path, release: matlab.release, version: matlab.version, source: "environment-cache", probeState: matlab.probeState, diagnostic: matlab.diagnostic } : null);
    setMatlabProbeState(matlab.probeState === "ready" ? "ready" : matlab.probeState === "failed" ? "failed" : "not-detected");
    setMatlabDiagnostic(matlab.diagnostic || (matlab.probeState === "ready" ? "MATLAB 已就绪" : "未检测到可启动的 MATLAB。"));
    setRuntimeState(value.runtime.state === "ready" ? "ready" : value.runtime.state === "optional" ? "not-detected" : "failed");
    setRuntimeDiagnostic(value.runtime.state === "ready" ? "Runtime 已就绪" : "Runtime 为可选链路");
    setEnvironmentScanBusy(false);
  }, []);

  useEffect(() => { if (environment) applyEnvironment(environment); }, [applyEnvironment, environment]);

  useEffect(() => {
    if (environment || onRefreshEnvironment) return;
    let cancelled = false;
    setEnvironmentScanBusy(true);
    void (async () => {
      try {
        const [matlabPayload, runtimePayload, bundled] = await Promise.all([api.engineeringInstallations(), api.engineeringRuntimeInstallations(), api.engineeringBundledRuntime()]);
        if (cancelled) return;
        const candidate = matlabPayload.installations.find(item => item.executable) || null;
        setRuntimeState(runtimePayload.runReady || bundled.usable ? "ready" : "not-detected");
        setRuntimeDiagnostic(bundled.usable ? bundled.diagnostic : "Runtime 为可选链路");
        if (!candidate?.executable) { setMatlabProbeState("not-detected"); setMatlabDiagnostic("未检测到可启动的 MATLAB。"); return; }
        setMatlabDiagnostic(`正在验证 ${candidate.release || "MATLAB"}…`);
        const probe = await api.engineeringProbe(candidate.executable, candidate.release || "");
        if (cancelled) return;
        setMatlabExecutable(probe.usable ? candidate.executable : "");
        setMatlabProbeState(probe.usable ? "ready" : "failed");
        setMatlabDiagnostic(probe.diagnostic || (probe.usable ? "MATLAB 已就绪" : "MATLAB 探测失败"));
        setMatlabInstallation({ executable: candidate.executable, release: candidate.release || "", version: candidate.version || probe.version || "", source: candidate.source || "legacy", probeState: probe.usable ? "ready" : "failed", diagnostic: probe.diagnostic });
      } catch (reason) { if (!cancelled) reportError(reason); }
      finally { if (!cancelled) setEnvironmentScanBusy(false); }
    })();
    return () => { cancelled = true; };
  }, [applyEnvironment, environment, onRefreshEnvironment, reportError]);

  const scanEngineeringEnvironment = useCallback(async () => {
    setEnvironmentScanBusy(true);
    try {
      if (onRefreshEnvironment) { applyEnvironment(await onRefreshEnvironment()); return; }
      const [matlabPayload, runtimePayload, bundled] = await Promise.all([api.engineeringInstallations(), api.engineeringRuntimeInstallations(), api.engineeringBundledRuntime()]);
      setRuntimeState(runtimePayload.runReady || bundled.usable ? "ready" : "not-detected");
      setRuntimeDiagnostic(bundled.usable ? bundled.diagnostic : "Runtime 为可选链路");
      const candidate = matlabPayload.installations.find(item => item.executable);
      if (!candidate?.executable) { setMatlabProbeState("not-detected"); setMatlabDiagnostic("未检测到可启动的 MATLAB。"); return; }
      const probe = await api.engineeringProbe(candidate.executable, candidate.release || "");
      setMatlabExecutable(probe.usable ? candidate.executable : "");
      setMatlabProbeState(probe.usable ? "ready" : "failed");
      setMatlabDiagnostic(probe.diagnostic || (probe.usable ? "MATLAB 已就绪" : "MATLAB 探测失败"));
      setMatlabInstallation({ executable: candidate.executable, release: candidate.release || "", version: candidate.version || probe.version || "", source: candidate.source || "legacy", probeState: probe.usable ? "ready" : "failed", diagnostic: probe.diagnostic });
    } catch (reason) { reportError(reason); }
    finally { setEnvironmentScanBusy(false); }
  }, [applyEnvironment, onRefreshEnvironment, reportError]);

  const selectMatlabDirectory = useCallback(async () => {
    setEnvironmentScanBusy(true);
    setMatlabProbeState("scanning");
    try {
      const root = await api.projectPickFolder();
      if (!root) return;
      const cleanRoot = root.replace(/[\\/]+$/, "");
      const executable = /[\\/]bin$/i.test(cleanRoot)
        ? `${cleanRoot}\\matlab.exe`
        : `${cleanRoot}\\bin\\matlab.exe`;
      const probe = await api.engineeringProbe(executable);
      setMatlabExecutable(executable);
      setMatlabProbeState(probe.usable ? "ready" : "failed");
      setMatlabDiagnostic(probe.diagnostic || (probe.usable ? "MATLAB 已就绪" : "所选目录未通过 MATLAB 探测"));
      setMatlabInstallation({ executable, release: "", version: probe.version || "", source: "manual", probeState: probe.usable ? "ready" : "failed", diagnostic: probe.diagnostic });
    } catch (reason) {
      setMatlabProbeState("failed");
      reportError(reason);
    } finally {
      setEnvironmentScanBusy(false);
    }
  }, [reportError]);

  useEffect(() => {
    const savedRun = window.localStorage.getItem("idesktop:last-engineering-run");
    if (!savedRun) return;
    void api.engineeringRunGet(savedRun).then(async value => {
      setRun(value);
      const history = await api.engineeringEvents(value.runId);
      setEvents(history.events.slice(-200));
    }).catch(() => window.localStorage.removeItem("idesktop:last-engineering-run"));
  }, []);
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
    const errors = validateOptimizationConfig(optimizationConfig);
    if (errors.length) { reportError(errors.join("；")); return; }
    if (lane === "local-matlab" && matlabProbeState !== "ready") { reportError("本机 MATLAB 尚未通过探测，不能开始优化。"); return; }
    setBottomActivitySignal(`engineering-run-${Date.now()}`);
    setRunBusy(true); setEvents([]);
    // Every new optimization opens the real MATLAB iteration view.
    setViewTab("iteration");
    try {
      if (lane !== "python-fem") await api.engineeringPreference(lane);
      const payload = buildEngineeringRunRequest(lane, projectId || "engineering-ui", runtimeProfileId);
      payload.task = engineeringTaskFromConfig(optimizationConfig);
      const created = await api.engineeringRun(payload);
      setRun(created);
      const seenEventKeys = new Set<string>();
      const acceptEvent = (event: Record<string, unknown>) => {
        const key = String(event.seq ?? `${event.type || "event"}:${event.iteration ?? ""}:${event.status ?? ""}:${event.text ?? ""}`);
        if (seenEventKeys.has(key)) return;
        seenEventKeys.add(key);
        setEvents(items => [...items, event].slice(-120));
      };
      const socket = api.engineeringStream(created.runId, acceptEvent);
      const eventPoller = window.setInterval(() => {
        void api.engineeringEvents(created.runId).then(value => value.events.forEach(acceptEvent)).catch(() => undefined);
      }, 500);
      try {
        for (;;) {
          await new Promise(resolve => window.setTimeout(resolve, 250));
          const current = await api.engineeringRunGet(created.runId);
          setRun(current);
          if (["completed", "failed", "cancelled"].includes(current.status)) {
            if (current.status === "completed") setCompletionSignal("engineering-completed-" + current.runId);
            break;
          }
        }
        const history = await api.engineeringEvents(created.runId);
        setEvents(history.events.slice(-80));
      } finally { window.clearInterval(eventPoller); socket.close(); }
    } catch (reason) { reportError(reason); }
    finally { setRunBusy(false); }
  }
  async function cancelRun() { if (run && !["completed", "failed", "cancelled"].includes(run.status)) setRun(await api.engineeringCancel(run.runId)); }
  async function exportReport() {
    if (!run) return;
    const name = window.prompt("请输入报告名称", `TopOptPilot-${run.runId}`)?.trim();
    if (!name) return;
    const chooseFolder = window.confirm("是否通过文件夹选择器指定报告生成位置？\n选择取消后可手动输入目录地址。");
    const outputDirectory = chooseFolder ? await api.projectPickFolder() : window.prompt("请输入报告生成目录的完整地址", projectRoot)?.trim();
    if (!outputDirectory) return;
    try {
      const ref = await api.engineeringReport(run.runId, name, outputDirectory);
      window.alert(`报告已生成：${ref.exportedPath || ref.relativePath}\nSHA-256: ${ref.sha256}`);
      setRun(await api.engineeringRunGet(run.runId));
    } catch (reason) { reportError(reason); }
  }
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
      terminalSeen.current = new Set(); setTerminalOutput([]); setTerminalSession(session.sessionId); setTerminalStatus(session.status); setBottomActivitySignal(`matlab-terminal-${session.sessionId}`);
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
  const receiveConversationHistory = useCallback((items: Conversation[], currentId: string) => {
    setConversationHistory(items);
    setActiveConversationId(currentId);
  }, []);

  async function createHistoryConversation() {
    try {
      const created = await api.conversationCreate("engineering", projectId || "engineering-unbound", "工程对话");
      setConversationHistory(items => [created, ...items]);
      setRequestedConversationId(created.id);
      setRightTab("history");
    } catch (reason) { reportError(reason); }
  }

  async function deleteHistoryConversation(id: string) {
    if (!window.confirm("删除该历史对话？工程运行和制品不会被删除。")) return;
    try {
      await api.conversationDelete(id);
      const remaining = conversationHistory.filter(item => item.id !== id);
      setConversationHistory(remaining);
      if (activeConversationId === id) setRequestedConversationId(remaining[0]?.id || "");
    } catch (reason) { reportError(reason); }
  }
  async function renameHistoryConversation(item: Conversation) {
    const title = window.prompt("新的对话名称", item.title)?.trim();
    if (!title || title === item.title) return;
    try {
      const updated = await api.conversationRename(item.id, title);
      setConversationHistory(items => items.map(value => value.id === item.id ? updated : value));
    } catch (reason) { reportError(reason); }
  }
  return <>
    <ParameterConfigurationDialog open={detailsOpen} config={optimizationConfig} lane={lane} busy={runBusy} matlabDiagnostic={matlabDiagnostic} runtimeDiagnostic={runtimeDiagnostic} onRefreshEnvironment={() => void scanEngineeringEnvironment()} onClose={() => setDetailsOpen(false)} onApply={(nextConfig, nextLane) => { setOptimizationConfig(nextConfig); setLane(nextLane); setDetailsOpen(false); }}/>
    <ResizableWorkspaceLayout mode="engineering"
    activitySignal={bottomActivitySignal}
    completionSignal={completionSignal}
    leftHeader={<b>工程工作区</b>}
    leftRail={<div className="left-rail-icons"><button aria-label="工作区与项目文件" title="工作区与项目文件" onClick={() => setRightTab("workspace")}><FolderOpen size={15}/></button><button aria-label="历史对话" title="历史对话" onClick={() => setRightTab("history")}><MessageCircle size={15}/></button></div>}
    left={<>
      <div className="v2-pane-title engineering-left-title"><div className="pane-actions"><button role="tab" aria-selected={rightTab === "workspace"} className={rightTab === "workspace" ? "active" : ""} onClick={() => setRightTab("workspace")}>工作区</button><button role="tab" aria-selected={rightTab === "history"} className={rightTab === "history" ? "active" : ""} onClick={() => setRightTab("history")}>历史对话</button></div></div>
      {rightTab === "workspace" ? <section className="engineering-left-workspace" aria-label="工作区与项目文件">
        {!projectRoot ? <button className="primary-button workspace-open-project workspace-open-project-top" aria-label="新建或打开研究项目" onClick={() => void openProject()}><FolderOpen size={14}/>打开项目文件夹</button> : null}
        <div className="sidebar-section-heading"><span>项目文件</span><div className="pane-actions"><button title="刷新项目" aria-label="刷新项目" disabled={!projectRoot || projectBusy || patchApplyBusy} onClick={() => void refreshProject()}><Activity size={14}/></button><button title="新建文件" aria-label="新建文件" disabled={patchApplyBusy} onClick={() => void createFile()}><FileCode2 size={14}/></button></div></div>
        <label className="v2-search"><Search size={14}/><input value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === "Enter") void searchProject(); }} placeholder="搜索文件与文本"/></label>
        <div className="project-root-label" title={projectRoot}>{projectRoot || "未打开项目文件夹"}</div>
        <ProjectTree entries={visibleFiles} selected={selectedFile} disabled={patchApplyBusy} onOpen={entry => void openFile(entry)}/>
      </section> : <section className="engineering-history-panel" aria-label="历史对话">
        <header><div><h4>历史对话</h4></div><button aria-label="新建历史对话" title="新建对话" onClick={() => void createHistoryConversation()}><Plus size={14}/></button></header>
        <div className="engineering-history-list">{conversationHistory.map(item => <div className={"engineering-history-row " + (activeConversationId === item.id ? "active" : "")} key={item.id}><button onClick={() => { setRequestedConversationId(item.id); setViewTab("chat"); }}><MessageCircle size={13}/><span>{item.title}<small>{relativeConversationTime(item.updatedAt, clockNow)}</small></span></button><button aria-label={"重命名对话 " + item.title} title="重命名对话" onClick={() => void renameHistoryConversation(item)}><Pencil size={12}/></button><button aria-label={"删除对话 " + item.title} title="删除对话" onClick={() => void deleteHistoryConversation(item.id)}>×</button></div>)}</div>
        {!conversationHistory.length ? <div className="v2-empty inspector-empty">暂无历史对话</div> : null}
      </section>}
    </>}
    center={<section className={`engineering-center-shell${viewTab === "chat" ? " chat-layout" : " has-compact-assistant"}`}>
      <nav className="v2-tabs engineering-view-tabs" role="tablist" aria-label="工程中央视图">
        <button role="tab" aria-selected={viewTab === "chat"} className={`tab ${viewTab === "chat" ? "active" : ""}`} onClick={() => setViewTab("chat")}><MessageCircle size={14}/>聊天</button>
        <button role="tab" aria-selected={viewTab === "code"} className={`tab ${viewTab === "code" ? "active" : ""}`} onClick={() => setViewTab("code")}><FileCode2 size={14}/>代码{dirty ? <i>●</i> : null}</button>
        <button role="tab" aria-selected={viewTab === "results"} className={`tab ${viewTab === "results" ? "active" : ""}`} onClick={() => setViewTab("results")}><Gauge size={14}/>结果</button>
        <button role="tab" aria-selected={viewTab === "iteration"} className={`tab ${viewTab === "iteration" ? "active" : ""}`} onClick={() => setViewTab("iteration")}><Activity size={14}/>迭代可视化</button>
        <button role="tab" aria-selected={viewTab === "compare"} className={`tab ${viewTab === "compare" ? "active" : ""}`} onClick={() => setViewTab("compare")}><Settings2 size={14}/>参数调整与对比</button>
        <div className="engineering-tab-actions"><span title={selectedFile?.relative_path}>{selectedFile?.relative_path || "未选择文件"}</span><button title="重命名当前文件" className="tab-action" onClick={() => void renameFile()} disabled={!selectedFile || dirty || patchApplyBusy}><Pencil size={13}/>重命名</button><button title="保存当前文件" className="tab-action" onClick={() => void saveFile()} disabled={!dirty || projectBusy || patchApplyBusy}><Save size={13}/>保存</button></div>
        <EngineeringRunButton busy={runBusy || run?.status === "queued" || run?.status === "running"} disabled={configErrors.length > 0 || (lane === "local-matlab" && matlabProbeState !== "ready")} label={"运行 " + solverLaneLabel(lane)} onRun={() => void startRun()} onStop={() => void cancelRun()}/>
        <div className="engineering-run-secondary-actions"><button aria-label="导出运行报告" title="生成运行报告" disabled={!run || runBusy} onClick={() => void exportReport()}><FileCode2 size={13}/></button><button aria-label="创建科研基线" title="创建科研基线" disabled={baselineBusy || !run || run.status !== "completed" || run.provenance.resultKind !== "solver" || !run.files.length} onClick={() => void createResearchBaseline()}><FlaskConical size={13}/></button></div>
      </nav>
      <div className={`engineering-view-content${viewTab === "chat" ? " chat-view-content" : ""}`} role="tabpanel">
        {viewTab === "chat" ? <EngineeringChatPanel projectId={projectId} selectedFile={selectedFile} run={run} config={optimizationConfig} onError={reportError} requestedConversationId={requestedConversationId} onHistoryChange={receiveConversationHistory} onApplySuggestedConfig={action => updateConfig(action.config)}/> : null}
        {viewTab === "code" ? <div className="monaco-host"><Suspense fallback={<div className="editor-loading">正在加载 Monaco 编辑器…</div>}><MonacoEditor language={languageFor(selectedFile?.relative_path)} value={selectedFile?.content || "% 打开项目后选择 UTF-8 源文件"} onChange={value => { if (selectedFile && !patchApplyBusy) { setSelectedFile({ ...selectedFile, content: value || "" }); setDirty(true); } }} options={{ readOnly: !selectedFile || projectBusy || patchApplyBusy, minimap: { enabled: false }, fontSize: 13, lineHeight: 22, automaticLayout: true, scrollBeyondLastLine: false, wordWrap: "off" }} theme="vs"/></Suspense></div> : null}
        {viewTab === "results" ? <ResultViewer run={run} onError={reportError}/> : null}
        {viewTab === "iteration" ? <EngineeringIterationView run={run} events={events} maxIterations={optimizationConfig.maxIterations}/> : null}
        {viewTab === "compare" ? <EngineeringComparisonWorkspace current={{ lane, nelx, nely, nelz, volfrac, maxIter }} run={run} onError={onError}/> : null}
      </div>
      {assistantOpen ? <section className="center-patch-panel" aria-label="PatchProposal 审批">
        <header><div><span className="eyebrow">CONTROLLED PATCH</span><h3>PatchProposal 审批</h3></div><button className="dialog-icon-button" aria-label="关闭补丁审批" onClick={() => setAssistantOpen(false)}>×</button></header>
        <p className="digest-line">{selectedFile?.sha256 || "未选择文件"}</p>
        <textarea className="assistant-instruction" value={assistantInstruction} disabled={patchApplyBusy} onChange={event => setAssistantInstruction(event.target.value)} placeholder="描述希望 Qwen 对当前已保存文件做出的修改" spellCheck={false}/>
        <label className="source-consent"><input type="checkbox" checked={assistantConsent} disabled={patchApplyBusy} onChange={event => setAssistantConsent(event.target.checked)}/>允许本次把当前文件内容发送给 DashScope/Qwen</label>
        <small className="privacy-note">代码修改只能生成候选差异，必须校验并由你确认应用。</small>
        <div className="assistant-actions"><button className="outline-button" disabled={assistantBusy || patchApplyBusy || dirty || !selectedFile || !assistantInstruction.trim() || !assistantConsent} onClick={() => void generatePatch()}>{assistantBusy ? "生成中…" : "由 Qwen 生成"}</button><button className="outline-button" disabled={patchApplyBusy || !patchDiff.trim()} onClick={() => void previewPatch()}>校验差异</button><button className="primary-button" disabled={!approvalTokenFor(patchApproval, projectRoot, proposal()) || dirty || patchApplyBusy} onClick={() => void applyPatch()}>{patchApplyBusy ? "应用中…" : "确认应用"}</button></div>
        <textarea className="patch-diff" value={patchDiff} disabled={patchApplyBusy} onChange={event => { setPatchDiff(event.target.value); setPatchApproval(null); }} placeholder="候选 unified diff；也可人工粘贴" spellCheck={false}/>
        {assistantStatus ? <small className="assistant-status">{assistantStatus}</small> : null}
      </section> : null}
      {viewTab !== "chat" ? <div className="engineering-composer">
        <div className="assistant-command-line"><input value={assistantInstruction} onChange={event => setAssistantInstruction(event.target.value)} onKeyDown={event => { if (event.key === "Enter") { setAssistantOpen(true); void generatePatch(); } }} placeholder="询问 TopOptPilot、生成代码补丁或输入命令…"/><button aria-label="发送给工程助手" disabled={assistantBusy || patchApplyBusy || !assistantInstruction.trim()} onClick={() => { setAssistantOpen(true); void generatePatch(); }}>{assistantBusy ? <Activity className="spin" size={14}/> : <Send size={14}/>}</button></div>
        {assistantStatus ? <small>{assistantStatus}</small> : null}
      </div> : null}
    </section>}
    bottom={<EngineeringBottomPanel
      terminalSession={terminalSession}
      terminalStatus={terminalStatus}
      terminalCommand={terminalCommand}
      terminalOutput={terminalOutput}
      events={events}
      run={run}


      matlabDiagnostic={matlabDiagnostic}
      runtimeDiagnostic={runtimeDiagnostic}
      onTerminalCommandChange={setTerminalCommand}

      onStartTerminal={() => void startTerminal()}
      onStopTerminal={() => void stopTerminal()}
      onSendTerminalCommand={() => void sendTerminalCommand()}


    />}
    right={<>
      <div className="v2-pane-title"><span>环境与参数</span><span className="permission">engineering</span></div>
      <div className="engineering-right-settings">
        <section className="engineering-settings-card environment-card" aria-label="环境配置">
          <header><div><span className="settings-card-kicker">ENVIRONMENT</span><h3>环境配置</h3></div><button aria-label="重新检测工程环境" title="重新检测 MATLAB 与 Runtime" disabled={environmentScanBusy} onClick={() => void scanEngineeringEnvironment()}><Activity className={environmentScanBusy ? "spin" : ""} size={15}/></button></header>
          <div className="environment-backend-selector" role="group" aria-label="执行后端">
            <button className={lane === "local-matlab" ? "active" : ""} aria-pressed={lane === "local-matlab"} disabled={runBusy} onClick={() => setLane("local-matlab")}>MATLAB</button>
            <button className={lane === "python-fem" ? "active" : ""} aria-pressed={lane === "python-fem"} disabled={runBusy} onClick={() => setLane("python-fem")}>Python</button>
          </div>
          {lane === "local-matlab" ? <><div className="environment-summary-row"><span><i className={`environment-state ${matlabProbeState}`}/><b>本机 MATLAB</b></span><strong>{matlabProbeState === "ready" ? matlabInstallation?.release || matlabInstallation?.version || "可用" : matlabProbeState === "scanning" ? "检测中" : "不可用"}</strong></div>
          <small className="environment-path" title={matlabExecutable || matlabDiagnostic}>{matlabExecutable || matlabDiagnostic}</small>
          {matlabProbeState !== "ready" ? <button className="outline-button environment-manual-path" disabled={environmentScanBusy} onClick={() => void selectMatlabDirectory()}><FolderOpen size={13}/>手动选择 MATLAB 目录</button> : null}
          <div className="environment-summary-row optional"><span><i className={`environment-state ${runtimeState}`}/><b>MATLAB Runtime</b></span><strong>{runtimeState === "ready" ? runtimeInstallation?.release || "可选可用" : "可选"}</strong></div>
          <small className="environment-path" title={runtimeInstallation?.path || runtimeDiagnostic}>{runtimeInstallation?.path || runtimeDiagnostic}</small></> : <div className="environment-summary-row"><span><i className="environment-state ready"/><b>内置 Python</b></span><strong>可用</strong></div>}
        </section>
        <section className="engineering-settings-card parameter-summary-card" aria-label="参数配置">
          <header><div><span className="settings-card-kicker">OPTIMIZATION</span><h3>参数配置</h3></div><button aria-label="打开参数配置" title="打开完整参数配置" onClick={() => setDetailsOpen(true)}><Settings2 size={15}/></button></header>
          <dl>
            <div><dt>求解维度</dt><dd>{optimizationConfig.dimension.toUpperCase()}</dd></div>
            <div><dt>网格</dt><dd>{optimizationConfig.nelx} × {optimizationConfig.nely}{optimizationConfig.dimension === "3d" ? ` × ${optimizationConfig.nelz}` : ""}</dd></div>
            <div><dt>工况</dt><dd>{optimizationConfig.bcType}</dd></div>
            <div><dt>体积分数</dt><dd>{optimizationConfig.volfrac}</dd></div>
            <div><dt>材料</dt><dd>{optimizationConfig.material.name}</dd></div>
            <div><dt>求解链路</dt><dd>{solverLaneLabel(lane)}</dd></div>
          </dl>
          {configErrors.length ? <p className="field-error">{configErrors[0]}</p> : null}
          <button className="primary-button open-parameter-dialog" onClick={() => setDetailsOpen(true)}><Settings2 size={14}/>打开详细参数</button>
        </section>
      </div>
    </>}
  />
  </>;
}
