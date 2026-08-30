import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, Bot, CheckCircle2, ChevronRight, FileJson2, FlaskConical, FolderOpen, ImagePlus, LoaderCircle, MessageCircle, Play, Plus, Send, Settings2, ShieldCheck, Trash2, X } from "lucide-react";
import { api } from "../../api";
import type { ConversationAttachment, ConversationMessage, EngineeringComparisonScheme, Experiment, Research, ResearchStateAction, ResearchWorkflowProgress } from "../../types";
import { DEFAULT_OPTIMIZATION_CONFIG, type OptimizationConfig } from "../../optimization-config";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { solverLaneLabel } from "../../workspace";
import { ConvergenceChart, ScalarMap } from "../engineering/ResultViewer";
import { normalizeResearchField, normalizeResearchHistory } from "./research-result";
import ParameterConfigurationDialog from "../engineering/ParameterConfigurationDialog";
import ResizableWorkspaceLayout from "../../components/ResizableWorkspaceLayout";
import { CHAT_IMAGE_MAX_COUNT, imageCandidateFromFile, useChatImageDrop, type DroppedImageCandidate } from "../../chat-image-drop";
import ResearchResultDialog from "./ResearchResultDialog";

type ArtifactIndex = { experiments: Array<{ experimentId: string; status: string; fidelity: string; backend: string; provenance: Record<string, string>; files: Array<{ relativePath: string; sizeBytes: number; sha256: string }>; metrics: Record<string, number | null> }> };
type CommandResult = { ok: boolean; message: string; action: string; data: Record<string, unknown> };
type Props = {
  researches: Research[];
  selected: Research | null;
  active?: Experiment;
  command: string;
  busy: boolean;
  safeMode: boolean;
  onCommand: (message?: string) => Promise<CommandResult | void> | void;
  onCreateResearch: () => void;
  onArchive: (id: string) => Promise<void>;
  onRestore: (id: string) => Promise<void>;
  onDecision: (id: string, action: "approve" | "reject") => void;
  onError: (message: string) => void;
  onSelect: (id: string) => Promise<void>;
  onSelectExperiment: (experiment: Experiment) => void;
  setCommand: (value: string) => void;
};
type PendingAttachment = ConversationAttachment & { preview: string };

export default function ResearchWorkspace(props: Props) {
  const { researches, selected, active, command, busy, safeMode, onCommand, onCreateResearch, onArchive, onRestore, onDecision, onError, onSelect, onSelectExperiment, setCommand } = props;
  const experiments = selected?.experiments ?? [];
  const [artifactIndex, setArtifactIndex] = useState<ArtifactIndex>({ experiments: [] });
  const [agentEvent, setAgentEvent] = useState("等待 Research 事件");
  const [streamText, setStreamText] = useState("");
  const [progressText, setProgressText] = useState("等待研究任务");
  const [autonomousBusy, setAutonomousBusy] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [researchActionBusy, setResearchActionBusy] = useState("");
  const [archived, setArchived] = useState<Research[]>([]);
  const [centerTab, setCenterTab] = useState<"chat" | "audit">("chat");
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [sending, setSending] = useState(false);
  const [researchConfig, setResearchConfig] = useState<OptimizationConfig>(DEFAULT_OPTIMIZATION_CONFIG);
  const [researchLane, setResearchLane] = useState<EngineeringSolverLane>("local-matlab");
  const [configOpen, setConfigOpen] = useState(false);
  const [goalDraft, setGoalDraft] = useState("");
  const [goalBusy, setGoalBusy] = useState(false);
  const [hypothesisDraft, setHypothesisDraft] = useState("");
  const [hypothesisBusy, setHypothesisBusy] = useState(false);
  const [suggestedAction, setSuggestedAction] = useState<ResearchStateAction | null>(null);
  const [completionSignal, setCompletionSignal] = useState("");
  const [schemePickerOpen, setSchemePickerOpen] = useState(false);
  const [engineeringSchemes, setEngineeringSchemes] = useState<EngineeringComparisonScheme[]>([]);
  const [selectedSchemeId, setSelectedSchemeId] = useState("");
  const [schemeImportBusy, setSchemeImportBusy] = useState(false);
  const [workflowProgress, setWorkflowProgress] = useState<ResearchWorkflowProgress | null>(selected?.workflow || null);
  const [resultExperiment, setResultExperiment] = useState<Experiment | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportName, setReportName] = useState("");
  const [reportDirectory, setReportDirectory] = useState("");
  const [reportOverwrite, setReportOverwrite] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportStatus, setReportStatus] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const dropZone = useRef<HTMLDivElement>(null);
  const messageList = useRef<HTMLDivElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const uploadingHashes = useRef(new Set<string>());
  const lastEventId = useRef(0);
  const recordedAgentEvents = useRef(new Set<number>());
  const selectedLoadGeneration = useRef(0);
  const metrics = useMemo(() => ({
    compliance: active?.result?.objective?.compliance,
    gray: active?.result?.quality?.gray_ratio,
    stress: active?.result?.quality?.maximum_von_mises,
    stressUnit: active?.result?.quality?.stress_unit_trusted ? "MPa" : "归一化",
  }), [active]);
  const resultView = useMemo(() => {
    const artifacts = (active?.result?.artifacts ?? {}) as Record<string, unknown>;
    return { density: normalizeResearchField(artifacts.density), history: normalizeResearchHistory(artifacts.history) };
  }, [active]);

  const persistAssistant = useCallback(async (content: string, source = "qwen", targetConversationId = conversationId) => {
    if (!targetConversationId || !content.trim()) return;
    const saved = await api.conversationMessage(targetConversationId, { role: "assistant", content: content.trim(), source });
    setMessages(items => items.some(item => item.id === saved.id) ? items : [...items, saved]);
    if (source === "qwen") setCompletionSignal("research-reply-" + saved.id);
  }, [conversationId]);

  useEffect(() => {
    const generation = ++selectedLoadGeneration.current;
    if (!selected) {
      setArtifactIndex({ experiments: [] });
      setConversationId("");
      setMessages([]);
      setResultExperiment(null);
      return;
    }
    let cancelled = false;
    setResultExperiment(null);
    setGoalDraft(selected.goal || "");
    setHypothesisDraft(selected.hypothesis || "");
    setSuggestedAction(null);
    setWorkflowProgress(selected.workflow || null);
    recordedAgentEvents.current.clear();
    lastEventId.current = Math.max(0, ...(selected.events || []).map(item => Number(item.id) || 0));
    Promise.all([
      api.researchArtifacts(selected.id),
      api.researchOptimizationConfig(selected.id),
      api.conversationList("research", selected.id),
    ]).then(async ([artifacts, config, conversations]) => {
      if (cancelled || generation !== selectedLoadGeneration.current) return;
      setArtifactIndex(artifacts);
      setResearchConfig(config);
      const id = conversations[0]?.id || "";
      if (cancelled || generation !== selectedLoadGeneration.current) return;
      setConversationId(id);
      const loadedMessages = id ? await api.conversationMessages(id) : [];
      if (cancelled || generation !== selectedLoadGeneration.current) return;
      setMessages(loadedMessages);
      followMessages.current = true;
      window.requestAnimationFrame(() => messageEnd.current?.scrollIntoView?.({ block: "end" }));
    }).catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [selected?.id, selected?.goal, onError]);

  useEffect(() => {
    if (centerTab !== "chat" || !followMessages.current) return;
    window.requestAnimationFrame(() => messageEnd.current?.scrollIntoView?.({ block: "end" }));
  }, [centerTab, messages, streamText, active?.id]);

  async function ensureConversation() {
    if (conversationId) return conversationId;
    if (!selected) throw new Error("请先选择 Research。");
    const created = await api.conversationCreate("research", selected.id, "科研对话");
    setConversationId(created.id);
    setMessages([]);
    return created.id;
  }

  useEffect(() => {
    if (!selected) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let refreshTimer = 0;
    let pollTimer = 0;

    const acceptEvents = (events: Array<Record<string, unknown>>) => {
      for (const value of events) {
        const id = Number(value.id) || 0;
        if (id) lastEventId.current = Math.max(lastEventId.current, id);
        setAgentEvent(String(value.title || value.kind || "research-event"));
        const kind = String(value.kind || "");
        const body = String(value.body || "");
        if (kind === "AGENT_MESSAGE" && body && !recordedAgentEvents.current.has(id)) {
          recordedAgentEvents.current.add(id);
          setStreamText("");
          void persistAssistant(body, "pi");
        }
      }
      window.clearTimeout(refreshTimer);
      refreshTimer = window.setTimeout(() => {
        if (!disposed) void onSelect(selected.id);
      }, 750);
    };
    const startPolling = () => {
      window.clearInterval(pollTimer);
      pollTimer = window.setInterval(() => {
        void api.researchEvents(selected.id, lastEventId.current).then(acceptEvents).catch(() => undefined);
      }, 1500);
    };

    void api.stream(selected.id).then(value => {
      if (disposed) { value.close(); return; }
      socket = value;
      socket.onmessage = event => {
        try {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          const type = String(payload.type || "");
          if (type === "events") acceptEvents((payload.events || []) as Array<Record<string, unknown>>);
          if (type === "agent_session") {
            const session = (payload.session || {}) as Record<string, unknown>;
            setStreamText(String(session.stream_text || ""));
            setAgentEvent(String(session.status || "Pi / Qwen"));
          }
          if (type === "progress") {
            const running = ((payload.experiments || []) as Array<Record<string, unknown>>)[0];
            if (running) setProgressText("MATLAB / MCP 实验 " + String(running.id || "") + " · 迭代 " + String(running.current_iteration || 0) + " · " + String(running.progress || 0) + "%");
          }
          if (type === "workflow_progress") setWorkflowProgress(payload.workflow as unknown as ResearchWorkflowProgress);
        } catch { setAgentEvent("收到无法解析的 Research 事件"); }
      };
      socket.onerror = () => {
        setAgentEvent("实时流中断，正在用事件游标补取");
        startPolling();
      };
    }).catch(reason => {
      if (!disposed) {
        setAgentEvent("实时流连接失败，正在用事件游标补取");
        startPolling();
        onError(String(reason));
      }
    });
    return () => {
      disposed = true;
      window.clearTimeout(refreshTimer);
      window.clearInterval(pollTimer);
      socket?.close();
    };
  }, [selected?.id, onSelect, onError, persistAssistant]);

  async function autonomous() {
    if (!selected) return;
    if (!selected.goal?.trim()) {
      onError("请先填写研究目标，再启动三方案比较与诊断流程。");
      return;
    }
    setAutonomousBusy(true);
    setProgressText("正在根据研究目标制定三套候选方案");
    try { await api.autonomous(selected.id); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setAutonomousBusy(false); }
  }
  async function compare() {
    if (!selected || experiments.length < 2) return;
    try {
      const [a, b] = experiments.slice(-2);
      const value = await api.researchCompare(selected.id, a.id, b.id);
      window.alert(JSON.stringify(value, null, 2));
    } catch (reason) { onError(String(reason)); }
  }
  async function pareto() {
    if (!selected) return;
    try { const value = await api.researchPareto(selected.id); window.alert("真实 Pareto 候选：" + value.length + " 个"); }
    catch (reason) { onError(String(reason)); }
  }
  async function createResearchArtifact(commandText: "/report" | "/export") {
    if (!selected) return;
    try {
      const value = await api.command(selected.id, commandText, active?.id);
      window.alert(value.message);
      await onSelect(selected.id);
    } catch (reason) { onError(String(reason)); }
  }
  function openReportExport() {
    if (!selected) return;
    const date = new Date().toISOString().slice(0, 10);
    setReportName(`TopOptPilot_${selected.name}_${date}`);
    setReportDirectory("");
    setReportOverwrite(false);
    setReportStatus("");
    setReportOpen(true);
  }
  async function chooseReportDirectory() {
    try {
      const directory = await api.projectPickFolder();
      if (directory) setReportDirectory(directory);
    } catch (reason) { onError(String(reason)); }
  }
  async function exportResearchReport() {
    if (!selected || !reportName.trim() || !reportDirectory.trim() || reportBusy) return;
    setReportBusy(true); setReportStatus("");
    try {
      const value = await api.researchReportExport(selected.id, {
        name: reportName.trim(), outputDirectory: reportDirectory.trim(),
        formats: ["markdown", "pdf"], overwrite: reportOverwrite,
      });
      const details = value.files.map(item =>
        `${item.path}\n${(item.sizeBytes / 1024).toFixed(1)} KB · SHA-256 ${item.sha256}`
      ).join("\n");
      setReportStatus(`已生成 Markdown、PDF 与图像资源。\nMarkdown：${value.markdownPath || "未生成"}\nPDF：${value.pdfPath || "未生成"}\n资源目录：${value.assetDirectory}${details ? `\n${details}` : ""}`);
    } catch (reason) {
      const message = String(reason);
      setReportStatus(message.includes("已存在") ? "同名报告已存在。确认“覆盖同名文件”后可重新生成。" : message);
    } finally { setReportBusy(false); }
  }
  async function toggleTrash() {
    const next = !trashOpen;
    setTrashOpen(next);
    if (!next) return;
    try { setArchived(await api.listResearch(true)); }
    catch (reason) { onError(String(reason)); }
  }
  async function archive(item: Research) {
    if (!window.confirm("将“" + item.name + "”移入回收站？科研证据和制品会保留。")) return;
    setResearchActionBusy(item.id);
    try { await onArchive(item.id); setArchived(await api.listResearch(true)); }
    catch (reason) { onError(String(reason)); }
    finally { setResearchActionBusy(""); }
  }
  async function restore(item: Research) {
    setResearchActionBusy(item.id);
    try { await onRestore(item.id); setArchived(items => items.filter(value => value.id !== item.id)); }
    catch (reason) { onError(String(reason)); }
    finally { setResearchActionBusy(""); }
  }

  async function uploadCandidates(candidates: DroppedImageCandidate[]) {
    if (!selected) return onError("请先选择 Research，再上传附件。");
    const existing = new Set(attachments.flatMap(item => item.sha256 ? [item.sha256] : []));
    const unique = candidates.filter(candidate => {
      if (existing.has(candidate.sha256) || uploadingHashes.current.has(candidate.sha256)) return false;
      existing.add(candidate.sha256);
      uploadingHashes.current.add(candidate.sha256);
      return true;
    });
    if (!unique.length) return;
    if (attachments.length + unique.length > CHAT_IMAGE_MAX_COUNT) {
      unique.forEach(item => uploadingHashes.current.delete(item.sha256));
      return onError("每条消息最多上传 4 个附件。");
    }
    setSending(true);
    try {
      const targetConversationId = await ensureConversation();
      const next: PendingAttachment[] = [];
      for (const candidate of unique) {
        const uploaded = await api.conversationAttachment(targetConversationId, {
          fileName: candidate.fileName,
          mediaType: candidate.mediaType,
          dataBase64: candidate.dataBase64,
        });
        next.push({ ...uploaded, fileName: candidate.fileName, sha256: uploaded.sha256 || candidate.sha256, preview: candidate.preview });
      }
      setAttachments(items => {
        const hashes = new Set(items.flatMap(item => item.sha256 ? [item.sha256] : []));
        return [...items, ...next.filter(item => !item.sha256 || !hashes.has(item.sha256))];
      });
    } catch (reason) { onError(String(reason)); }
    finally {
      unique.forEach(item => uploadingHashes.current.delete(item.sha256));
      setSending(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function uploadFiles(files: FileList | null) {
    if (!files?.length) return;
    try { await uploadCandidates(await Promise.all(Array.from(files).map(imageCandidateFromFile))); }
    catch (reason) { onError(String(reason)); }
  }
  const { dragActive, handlers: dropHandlers } = useChatImageDrop({
    zoneRef: dropZone,
    disabled: sending || busy || !selected || centerTab !== "chat",
    onCandidates: uploadCandidates,
    onError,
  });
  async function sendResearchMessage() {
    const value = command.trim() || (attachments.length ? "请分析这些附件与当前研究目标的关系" : "");
    if (!selected || !value || sending || busy) return;
    const targetConversationId = await ensureConversation();
    const attachmentIds = attachments.map(item => item.id);
    setSending(true);
    setCommand("");
    setAttachments([]);
    try {
      const user = await api.conversationMessage(targetConversationId, { role: "user", content: value, attachmentIds });
      setMessages(items => [...items, user]);
      if (attachmentIds.length) {
        const response = await api.researchVisionChat(selected.id, value, attachmentIds);
        setSuggestedAction(response.actions?.[0] || null);
        const reply = response.reply || (response.actions?.length ? "已生成可确认的研究状态建议。" : response.source === "not_configured" ? "当前未配置可用的 Qwen 凭据。" : "当前模型无法处理该附件，草稿已保留。");
        await persistAssistant(reply, response.source, targetConversationId);
      } else if (!value.startsWith("/")) {
        setProgressText("正在读取 Research State 并生成真实回复");
        const response = await api.researchChat(selected.id, value, active?.id);
        setSuggestedAction(response.actions?.[0] || null);
        const reply = response.reply || (response.actions?.length
          ? "已生成可确认的研究状态建议。"
          : response.source === "not_configured"
            ? "当前未配置 Qwen 凭据。科研对话已保留，但不会生成伪造回复。"
            : "当前模型不可用，科研对话已保留。");
        await persistAssistant(reply, response.source, targetConversationId);
      } else {
        setProgressText("正在理解目标并读取 Research State");
        const response = await onCommand(value);
        const acknowledgement = response?.message || "";
        if (acknowledgement && !acknowledgement.includes("已发送给常驻 Pi Research Agent") && !acknowledgement.includes("Sent to the persistent Pi")) {
          await persistAssistant(acknowledgement, safeMode ? "safe_mode" : "qwen", targetConversationId);
        }
      }
    } catch (reason) { onError(String(reason)); }
    finally { setSending(false); }
  }

  async function saveGoal() {
    if (!selected || !goalDraft.trim() || goalDraft.trim() === selected.goal) return;
    setGoalBusy(true);
    try { await api.saveResearchGoal(selected.id, goalDraft.trim()); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setGoalBusy(false); }
  }

  async function saveHypothesis() {
    if (!selected || !hypothesisDraft.trim() || hypothesisDraft.trim() === (selected.hypothesis || "")) return;
    setHypothesisBusy(true);
    try { await api.saveResearchHypothesis(selected.id, hypothesisDraft.trim()); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setHypothesisBusy(false); }
  }

  async function applySuggestion() {
    if (!selected || !suggestedAction) return;
    try {
      const value = await api.applyResearchSuggestion(selected.id, suggestedAction);
      if (value.optimizationConfig) setResearchConfig(value.optimizationConfig);
      setGoalDraft(value.research.goal || "");
      setHypothesisDraft(value.research.hypothesis || "");
      setSuggestedAction(null);
      await onSelect(selected.id);
    } catch (reason) { onError(String(reason)); }
  }

  async function saveConfig(config: OptimizationConfig, lane: EngineeringSolverLane) {
    if (!selected) return;
    try {
      const saved = await api.saveResearchOptimizationConfig(selected.id, config);
      setResearchConfig(saved);
      setResearchLane(lane);
      setConfigOpen(false);
      await onSelect(selected.id);
    } catch (reason) { onError(String(reason)); }
  }

  async function openSchemePicker() {
    if (!selected) return onError("请先创建或选择 Research，再导入工程方案。");
    setSchemeImportBusy(true);
    try {
      const schemes = (await api.engineeringComparisonSchemes()).filter(item => item.integrity === "verified" && item.run?.status === "completed");
      setEngineeringSchemes(schemes);
      setSelectedSchemeId(schemes[0]?.id || "");
      setSchemePickerOpen(true);
    } catch (reason) {
      onError(String(reason));
    } finally {
      setSchemeImportBusy(false);
    }
  }

  async function importEngineeringScheme() {
    if (!selected || !selectedSchemeId) return;
    setSchemeImportBusy(true);
    try {
      const value = await api.researchImportEngineeringScheme(selected.id, selectedSchemeId);
      setResearchConfig(value.optimizationConfig);
      const targetConversationId = await ensureConversation();
      const systemMessage = await api.conversationMessage(targetConversationId, {
        role: "system",
        content: `已导入工程方案“${value.baseline.name}”（Run ${value.baseline.runId}）作为真实科研基线；参数已填入，但尚未启动实验。`,
        source: "engineering-baseline",
      });
      setMessages(items => [...items, systemMessage]);
      setSchemePickerOpen(false);
      await onSelect(selected.id);
    } catch (reason) {
      onError(String(reason));
    } finally {
      setSchemeImportBusy(false);
    }
  }

  const leftPane = <><div className="v2-pane-title"><span>{trashOpen ? "回收站" : "Research"}</span><span className="count">{trashOpen ? archived.length : researches.length}</span><div className="research-list-actions"><button aria-label={trashOpen ? "返回 Research 列表" : "打开 Research 回收站"} title={trashOpen ? "返回 Research 列表" : "回收站"} onClick={() => void toggleTrash()}>{trashOpen ? <ChevronRight size={13}/> : <Trash2 size={13}/>}</button>{!trashOpen ? <button className="primary-button compact" onClick={onCreateResearch}><FlaskConical size={13}/>新建</button> : null}</div></div>
    <div className="research-list">{(trashOpen ? archived : researches).map(item => <div className={"research-row-shell " + (selected?.id === item.id && !trashOpen ? "active" : "")} key={item.id}><button className="research-row research-select" disabled={trashOpen} onClick={() => void onSelect(item.id)}><FlaskConical size={15}/><span><b>{item.name}</b><small>{item.status} · {item.id}</small></span><ChevronRight size={14}/></button><button className="research-row-action" disabled={researchActionBusy === item.id} aria-label={(trashOpen ? "恢复" : "删除") + item.name} title={trashOpen ? "恢复 Research" : "移入回收站"} onClick={() => void (trashOpen ? restore(item) : archive(item))}>{researchActionBusy === item.id ? <LoaderCircle className="spin" size={14}/> : trashOpen ? <ArchiveRestore size={14}/> : <Trash2 size={14}/>}</button></div>)}</div>
    {!((trashOpen ? archived : researches).length) ? <div className="research-list-empty">{trashOpen ? "回收站为空" : "尚无 Research"}</div> : null}
    <div className="research-evidence"><h4>证据索引</h4><p>Research State 是唯一权威来源。移入回收站不会删除实验、审批、报告或制品。</p><div className="budget-line"><span>预算</span><b>{selected?.budget_used ?? 0}/{selected?.budget_total ?? 0}</b></div><button className="primary-button research-final-result-button" disabled={!selected?.best_experiment} title={selected?.best_experiment ? "查看最终方案" : "尚无真实最终方案"} onClick={() => setResultExperiment(selected?.best_experiment || null)}>查看最终方案</button></div></>;
  const runningExperiment = experiments.find(item => ["RUNNING", "WAITING", "QUEUED"].includes(String(item.status).toUpperCase()));
  const pendingDecision = selected?.decisions?.find(decision => decision.status === "PENDING");
  const stage = runningExperiment ? progressText : pendingDecision ? "等待 Policy / F0-F3 审批" : streamText ? "正在分析结果并生成回复" : autonomousBusy ? "正在制定实验方案" : "等待下一条科研指令";

  return <>
    <ParameterConfigurationDialog open={configOpen} config={researchConfig} lane={researchLane} busy={Boolean(runningExperiment)} matlabDiagnostic="科研 MATLAB 任务将通过 Policy、审批和 MATLAB MCP 执行。" runtimeDiagnostic="Runtime 为可选工程链路，不替代科研审批。" onClose={() => setConfigOpen(false)} onApply={(config, lane) => void saveConfig(config, lane)}/>
    <ResearchResultDialog researchId={selected?.id || ""} experiment={resultExperiment} onClose={() => setResultExperiment(null)}/>
    {schemePickerOpen ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="engineering-scheme-import-dialog suggestion-dialog" role="dialog" aria-modal="true" aria-label="导入工程方案"><header><b>导入工程方案</b><button className="dialog-icon-button" title="关闭" aria-label="关闭工程方案导入" onClick={() => setSchemePickerOpen(false)}><X size={14}/></button></header>{engineeringSchemes.length ? <div className="engineering-scheme-import-list">{engineeringSchemes.map(item => <label className={selectedSchemeId === item.id ? "active" : ""} key={item.id}><input type="radio" name="engineering-scheme" checked={selectedSchemeId === item.id} onChange={() => setSelectedSchemeId(item.id)}/><span><b>{item.name}</b><small>Run {item.runId} · {String(item.config.dimension || "3d").toUpperCase()} · {String(item.run?.provenance.backend || item.run?.lane || "solver")}</small><small>柔度 {item.run?.metrics.compliance?.toFixed?.(4) ?? "—"} · 体积分数 {item.run?.metrics.volumeFraction?.toFixed?.(4) ?? "—"} · 灰度率 {item.run?.metrics.grayRatio?.toFixed?.(4) ?? "—"}</small></span></label>)}</div> : <p>没有完整性已验证且运行完成的工程方案。</p>}<footer><button className="outline-button" onClick={() => setSchemePickerOpen(false)}>取消</button><button className="primary-button" disabled={!selectedSchemeId || schemeImportBusy} onClick={() => void importEngineeringScheme()}>{schemeImportBusy ? "导入中…" : "导入并填入"}</button></footer></section></div> : null}
    {reportOpen ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="research-report-dialog suggestion-dialog" role="dialog" aria-modal="true" aria-label="导出科研报告"><header><b>导出科研报告</b><button className="dialog-icon-button" title="关闭" aria-label="关闭科研报告导出" onClick={() => setReportOpen(false)}><X size={14}/></button></header><label>报告名称<input maxLength={120} value={reportName} onChange={event => setReportName(event.target.value)}/></label><label>生成位置<div className="report-directory-field"><input value={reportDirectory} placeholder="输入完整目录，或点击右侧选择文件夹" onChange={event => setReportDirectory(event.target.value)}/><button className="dialog-icon-button" title="选择文件夹" aria-label="选择报告生成文件夹" onClick={() => void chooseReportDirectory()}><FolderOpen size={15}/></button></div></label><p>默认同时生成 Markdown、PDF 和配套黑白图像资源。</p><label className="report-overwrite-confirm"><input type="checkbox" checked={reportOverwrite} onChange={event => setReportOverwrite(event.target.checked)}/>覆盖同名报告和资源目录</label>{reportStatus ? <div className="report-export-status">{reportStatus}</div> : null}<footer><button className="outline-button" disabled={reportBusy} onClick={() => setReportOpen(false)}>关闭</button><button className="primary-button" disabled={reportBusy || !reportName.trim() || !reportDirectory.trim()} onClick={() => void exportResearchReport()}>{reportBusy ? <LoaderCircle className="spin" size={14}/> : null}{reportBusy ? "生成中…" : "生成报告"}</button></footer></section></div> : null}
    <ResizableWorkspaceLayout mode="research"
      activitySignal={runningExperiment ? "research-" + (selected?.id || "none") + "-" + runningExperiment.id : autonomousBusy ? "research-planning-" + (selected?.id || "none") : ""}
      completionSignal={completionSignal}
      leftRail={<div className="left-rail-icons"><button aria-label="研究项目" title="研究项目"><FlaskConical size={15}/></button><button aria-label="科研对话" title="科研对话" onClick={() => setCenterTab("chat")}><MessageCircle size={15}/></button><button aria-label="科研审批" title="科研审批" onClick={() => setCenterTab("audit")}><ShieldCheck size={15}/></button></div>}
      left={leftPane}
      center={<section className="v2-center research-center research-chat-workspace">
        <div className="research-header"><div><span className="eyebrow">AI SCIENTIST WORKSPACE</span><h1>{selected?.name || "选择一个 Research"}</h1></div><div className="research-header-actions"><span className={"agent-mode " + (safeMode ? "safe" : "online")}>{safeMode ? "规则 Safe Mode" : "Pi / Qwen"}</span><button className="primary-button" disabled={!selected || autonomousBusy || Boolean(runningExperiment) || String(selected?.status || "").toUpperCase() === "RUNNING"} onClick={() => void autonomous()}>{autonomousBusy ? <LoaderCircle className="spin"/> : <Play size={14}/>}运行自主研究</button></div></div>
        <nav className="v2-tabs research-center-tabs" role="tablist"><button role="tab" aria-selected={centerTab === "chat"} className={"tab" + (centerTab === "chat" ? " active" : "")} onClick={() => setCenterTab("chat")}><MessageCircle size={14}/>科研对话</button><button role="tab" aria-selected={centerTab === "audit"} className={"tab" + (centerTab === "audit" ? " active" : "")} onClick={() => setCenterTab("audit")}><ShieldCheck size={14}/>过程 / 审计</button></nav>
        <div className="research-stage-strip"><span className="connection-dot"/><b>{stage}</b><small>{agentEvent}</small></div>
        {workflowProgress && workflowProgress.stage !== "idle" ? <section className="research-workflow-progress" aria-label="自主研究阶段进度"><header><b>第 {workflowProgress.round} 轮</b><span>{workflowProgress.percent}%</span></header><div className="research-workflow-track"><i style={{ width: `${workflowProgress.percent}%` }}/></div><small>{workflowProgress.steps.find(item => item.status === "active")?.label || (workflowProgress.percent === 100 ? "本轮已完成" : "等待下一阶段")}</small></section> : null}
        {centerTab === "chat" ? <div ref={dropZone} className={"research-chat-main chat-drop-zone" + (dragActive ? " drag-active" : "")} {...dropHandlers}>
          {dragActive ? <div className="chat-drop-overlay"><ImagePlus size={20}/><b>松开以上传附件</b><span>图片、PDF、Word、Excel、SVG、文本 · 单个不超过 10 MB</span></div> : null}
          <div ref={messageList} className="chat-message-list research-message-list" onScroll={() => { const node = messageList.current; if (node) followMessages.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80; }}>{messages.map(item => <article className={"chat-message " + item.role} key={item.id}><span className="chat-avatar">{item.role === "assistant" ? <Bot size={14}/> : "你"}</span><div><p>{item.content}</p>{item.attachments?.length ? <small>{item.attachments.length} 个附件 · 已保存在该 Research 会话</small> : null}{item.source ? <small>{item.source}</small> : null}</div></article>)}{streamText ? <article className="chat-message assistant streaming"><span className="chat-avatar"><Bot size={14}/></span><div><p>{streamText}</p><small>Pi / Qwen 正在生成真实回复…</small></div></article> : null}{!messages.length && !streamText ? <div className="chat-empty"><Bot size={28}/><b>直接描述研究目标或下一项实验</b><span>AI 会读取 Research State，提案仍需通过 Policy 与 F0-F3 审批。</span></div> : null}{active ? <section className="research-result-panel"><header><span>真实实验结果 · {active.id}</span><small>{active.fidelity} · {active.backend} · {active.status}</small></header><div className="result-plots"><section><h4>密度场</h4><ScalarMap values={resultView.density} mode="density"/></section><section><h4>柔度收敛</h4><ConvergenceChart points={resultView.history}/></section></div></section> : null}<div ref={messageEnd} className="chat-message-end" aria-hidden="true"/></div>
          {suggestedAction ? <div className="suggestion-dialog-backdrop" role="presentation"><ResearchSuggestionCard action={suggestedAction} currentGoal={selected?.goal || ""} currentHypothesis={selected?.hypothesis || ""} currentConfig={researchConfig} onApply={() => void applySuggestion()} onCancel={() => setSuggestedAction(null)} /></div> : null}
          <footer className="chat-composer research-chat-composer">{attachments.length ? <div className="chat-attachment-preview">{attachments.map(item => <figure key={item.id}>{item.preview ? <img src={item.preview} alt={item.fileName || "待发送附件"}/> : <span className="attachment-file-name">{item.fileName || "附件"}</span>}<button aria-label="移除附件" onClick={() => setAttachments(values => values.filter(value => value.id !== item.id))}><X size={12}/></button></figure>)}</div> : null}<div><button type="button" className="chat-composer-action scheme-import-button" aria-label="导入工程方案" title="导入工程方案" onClick={() => void openSchemePicker()} disabled={!selected || sending || schemeImportBusy}><Plus size={15}/></button><input ref={fileInput} hidden type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf,.docx,.xlsx,.txt,.md,.csv" multiple onChange={event => void uploadFiles(event.target.files)}/><button type="button" className="chat-composer-action" aria-label="上传科研附件" title="上传附件" onClick={() => fileInput.current?.click()} disabled={sending}><ImagePlus size={15}/></button><textarea value={command} onChange={event => setCommand(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendResearchMessage(); } }} placeholder="描述目标、询问证据或提出下一项实验…"/><button className="chat-composer-action" aria-label="发送科研消息" title="发送" onClick={() => void sendResearchMessage()} disabled={(!command.trim() && !attachments.length) || sending || busy}>{sending || busy ? <LoaderCircle className="spin" size={15}/> : <Send size={15}/>}</button></div></footer>
        </div> : <div className="research-audit-main">{selected?.events?.slice(-30).map(event => <article className="timeline-item" key={event.id}><span className="timeline-icon"><CheckCircle2 size={14}/></span><div><small>{event.kind} · {new Date(event.created_at).toLocaleTimeString()}</small><h3>{event.title}</h3><p>{event.body}</p></div></article>)}{selected?.decisions?.filter(decision => decision.status === "PENDING").map(decision => <article className="decision-card" key={decision.id}><header><ShieldCheck size={14}/>Policy 审批 <span>{decision.risk}</span></header><h3>{decision.proposal?.fidelity || "实验提案"}</h3><p>{decision.reason}</p><div><button className="approve" onClick={() => onDecision(decision.id, "approve")}>批准并提交</button><button onClick={() => onDecision(decision.id, "reject")}>拒绝</button></div></article>)}</div>}
      </section>}
      bottom={<section className="research-bottom-progress"><header><b>科研执行进度</b><span>{workflowProgress ? `第 ${workflowProgress.round} 轮 · ${workflowProgress.percent}%` : stage}</span></header><div className="research-workflow-steps">{(workflowProgress?.steps || []).map(step => <article className={"research-workflow-step " + step.status} key={step.id}><header><span className="workflow-step-state"/><b>{step.label}</b><small>{step.status === "completed" ? "已完成" : step.status === "active" ? "进行中" : step.status === "failed" ? "失败" : "等待"}</small></header>{step.result ? <p><strong>结果</strong>{step.result}</p> : null}{step.reflection ? <p><strong>反思</strong>{step.reflection}</p> : null}{step.evidenceIds.length ? <p><strong>证据</strong>{step.evidenceIds.join(" · ")}</p> : null}{step.nextAction ? <p><strong>下一步</strong>{step.nextAction}</p> : null}</article>)}{!workflowProgress ? <div className="research-progress-empty">尚未启动自主研究。</div> : null}</div></section>}
      right={<>
        <div className="v2-pane-title"><span>研究状态</span><span className="permission research">research</span></div>
        {selected ? <>
          <section className="inspector-card research-goal-card">
            <h4>研究目标</h4>
            <textarea aria-label="研究目标" placeholder="填写希望达成的科研目标" value={goalDraft} onChange={event => setGoalDraft(event.target.value)} maxLength={2000}/>
            <button className="primary-button" disabled={goalBusy || !goalDraft.trim() || goalDraft.trim() === selected.goal} onClick={() => void saveGoal()}>{goalBusy ? "保存中…" : "保存目标"}</button>
          </section>
          <section className="inspector-card research-hypothesis-card">
            <h4>研究假设</h4>
            <textarea aria-label="研究假设" placeholder="填写待验证的机制、趋势或因果假设" value={hypothesisDraft} onChange={event => setHypothesisDraft(event.target.value)} maxLength={4000}/>
            <button className="primary-button" disabled={hypothesisBusy || !hypothesisDraft.trim() || hypothesisDraft.trim() === (selected.hypothesis || "")} onClick={() => void saveHypothesis()}>{hypothesisBusy ? "保存中…" : "保存假设"}</button>
          </section>
          <section className="inspector-card research-config-card">
            <header className="inspector-card-heading"><h4>参数配置</h4><button aria-label="打开科研详细参数" onClick={() => setConfigOpen(true)}><Settings2 size={14}/></button></header>
            <div className="configuration-summary"><code>{researchConfig.dimension.toUpperCase()} · {researchConfig.nelx}×{researchConfig.nely}×{researchConfig.dimension === "2d" ? 1 : researchConfig.nelz}</code><code>{researchConfig.bcType} · volfrac {researchConfig.volfrac}</code><code>{researchConfig.material.name}</code><code>{solverLaneLabel(researchLane)}</code></div>
          </section>
          <section className="inspector-card research-results-card">
            <h4>结果呈现</h4>
            {active ? <><div className="run-heading"><div><h3>{active.id}</h3><small>{active.fidelity} · {active.backend}</small></div><span className={"status status-" + active.status.toLowerCase()}>{active.status}</span></div><div className="metric-cards"><Metric label="柔度" value={metrics.compliance}/><Metric label="灰度率" value={metrics.gray}/><Metric label={`最大应力（${metrics.stressUnit}）`} value={metrics.stress}/></div>{active.error ? <p className="error-text">{active.error}</p> : null}</> : <p className="inspector-empty-copy">尚无科研实验结果。</p>}
            <div className="research-plan-flow" aria-label="三方案科研流程"><span className="active">1 · 三方案</span><span>2 · 真实实验比较</span><span>3 · 优选路线</span><span>4 · 问题诊断</span><span>5 · 下一轮建议</span></div>
            <div className="research-artifact-list">{artifactIndex.experiments.slice(-5).map(item => <div className="artifact-row" key={item.experimentId}><span><FileJson2 size={12}/>{item.experimentId} · {item.backend}</span><small>{item.files.length} 个文件 · {item.provenance.resultKind || "unknown"}</small></div>)}</div>
            {experiments.length ? <div className="research-result-experiments"><h5>实验</h5>{experiments.slice(-8).map(experiment => <div className="experiment-row-shell" key={experiment.id}><button className={"experiment-row " + (active?.id === experiment.id ? "active" : "")} onClick={() => onSelectExperiment(experiment)}><span className="experiment-status"/><span>{experiment.id}<small>{solverLaneLabel(experiment.backend === "matlab" ? "matlab-mcp" : "python-fem")} · {experiment.fidelity}</small></span></button></div>)}</div> : null}
            <div className="inspector-actions artifact-actions"><button className="outline-button" onClick={() => void pareto()}>查看 Pareto</button><button className="outline-button" disabled={experiments.length < 2} onClick={() => void compare()}>比较实验</button><button className="outline-button" onClick={openReportExport}>生成报告</button><button className="outline-button" onClick={() => void createResearchArtifact("/export")}>复现包</button></div>
          </section>
        </> : <div className="inspector-empty"><FlaskConical size={24}/><span>选择或新建 Research</span></div>}
      </>}
    />
  </>;
}

function ResearchSuggestionCard({ action, currentGoal, currentHypothesis, currentConfig, onApply, onCancel }: { action: ResearchStateAction; currentGoal: string; currentHypothesis: string; currentConfig: OptimizationConfig; onApply: () => void; onCancel: () => void }) {
  const rows = action.changedFields.map(field => {
    if (field === "goal") return { label: "研究目标", current: currentGoal || "未填写", next: action.goal || "—" };
    if (field === "hypothesis") return { label: "研究假设", current: currentHypothesis || "未填写", next: action.hypothesis || "—" };
    const current = `${currentConfig.dimension.toUpperCase()} · ${currentConfig.nelx}×${currentConfig.nely}×${currentConfig.nelz} · volfrac ${currentConfig.volfrac}`;
    const nextConfig = action.optimizationConfig;
    const next = nextConfig ? `${nextConfig.dimension.toUpperCase()} · ${nextConfig.nelx}×${nextConfig.nely}×${nextConfig.nelz} · volfrac ${nextConfig.volfrac}` : "—";
    return { label: "参数配置", current, next };
  });
  return <section className="research-suggestion-card suggestion-dialog" role="region" aria-label="Agent 研究状态建议"><header><b>Agent 研究状态建议</b><button className="dialog-icon-button" aria-label="取消研究建议" title="取消" onClick={onCancel}><X size={14}/></button></header>{action.rationale ? <p>{action.rationale}</p> : null}<div>{rows.map(row => <article key={row.label}><b>{row.label}</b><span>{row.current}</span><i>→</i><strong>{row.next}</strong></article>)}</div><footer><button className="outline-button" onClick={onCancel}>取消</button><button className="primary-button" onClick={onApply}>批准并填入</button></footer></section>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div><small>{label}</small><b>{typeof value === "number" ? value.toFixed(3) : String(value ?? "—")}</b></div>;
}
