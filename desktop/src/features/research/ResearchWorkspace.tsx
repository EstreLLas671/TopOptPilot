import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArchiveRestore, Bot, CheckCircle2, ChevronRight, FileJson2, FlaskConical, FolderOpen, ImagePlus, LoaderCircle, MessageCircle, Play, Plus, Send, Settings2, ShieldCheck, Square, Trash2, X } from "lucide-react";
import { api, DEMO_EDITION } from "../../api";
import type { ConversationAttachment, ConversationMessage, EngineeringComparisonScheme, Experiment, Research, ResearchProposal, ResearchStageGate, ResearchStateAction, ResearchWorkflowProgress } from "../../types";
import { DEFAULT_OPTIMIZATION_CONFIG, normalizeOptimizationConfig, type OptimizationConfig } from "../../optimization-config";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { solverLaneLabel } from "../../workspace";
import { ConvergenceChart, ScalarMap } from "../engineering/ResultViewer";
import InteractiveVolumeView, { type ViewState } from "../engineering/InteractiveVolumeView";
import { asFortranVolume, readFloat32LittleEndian, type MatlabVolume } from "../engineering/matlab-artifact";
import { normalizeResearchField, normalizeResearchHistory } from "./research-result";
import ParameterConfigurationDialog from "../engineering/ParameterConfigurationDialog";
import ResizableWorkspaceLayout from "../../components/ResizableWorkspaceLayout";
import { CHAT_IMAGE_MAX_COUNT, imageCandidateFromFile, useChatImageDrop, type DroppedImageCandidate } from "../../chat-image-drop";
import ResearchResultDialog from "./ResearchResultDialog";

const normalizeStep = (value: unknown): ResearchStageGate["stageCode"] => {
  const code = String(value || "STEP1").toUpperCase().split(/\s+/)[0];
  return ({ F0:"STEP1", F1:"STEP2", F2:"STEP3", F3:"STEP4" } as Record<string,ResearchStageGate["stageCode"]>)[code]
    || (code as ResearchStageGate["stageCode"]);
};
const stepLabel = (value: unknown) => `Step${normalizeStep(value).replace("STEP", "")}`;

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
type ResearchDraft = {
  goal:string; hypothesis:string; config:OptimizationConfig;
  dirty:{goal:boolean;hypothesis:boolean;config:boolean};
};

export default function ResearchWorkspace(props: Props) {
  const { researches, selected, active, command, busy, safeMode, onCommand, onCreateResearch, onArchive, onRestore, onDecision, onError, onSelect, onSelectExperiment, setCommand } = props;
  const experiments = selected?.experiments ?? [];
  const [artifactIndex, setArtifactIndex] = useState<ArtifactIndex>({ experiments: [] });
  const [agentEvent, setAgentEvent] = useState("等待 Research 事件");
  const [streamText, setStreamText] = useState("");
  const [progressText, setProgressText] = useState("等待研究任务");
  const [autonomousBusy, setAutonomousBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
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
  const [suggestedActions, setSuggestedActions] = useState<Array<ResearchStateAction & { messageId: string }>>([]);
  const [suggestionEditorOpen, setSuggestionEditorOpen] = useState(false);
  const [completionSignal, setCompletionSignal] = useState("");
  const [schemePickerOpen, setSchemePickerOpen] = useState(false);
  const [engineeringSchemes, setEngineeringSchemes] = useState<EngineeringComparisonScheme[]>([]);
  const [selectedSchemeId, setSelectedSchemeId] = useState("");
  const [schemeImportBusy, setSchemeImportBusy] = useState(false);
  const [workflowProgress, setWorkflowProgress] = useState<ResearchWorkflowProgress | null>(selected?.workflow || null);
  const [stageDecisionBusy, setStageDecisionBusy] = useState(false);
  const [candidatePlanBusy, setCandidatePlanBusy] = useState(false);
  const [finishBusy, setFinishBusy] = useState(false);
  const [resultExperiment, setResultExperiment] = useState<Experiment | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportName, setReportName] = useState("");
  const [reportDirectory, setReportDirectory] = useState("");
  const [reportOverwrite, setReportOverwrite] = useState(false);
  const [reportBusy, setReportBusy] = useState(false);
  const [reportStatus, setReportStatus] = useState("");
  const [reportPreview, setReportPreview] = useState<{markdown:string;markdownPath:string;pdfPath:string}|null>(null);
  const [visualizationManifest, setVisualizationManifest] = useState<import("../../types").ResearchVisualizationManifest | null>(null);
  const [densityVolume, setDensityVolume] = useState<MatlabVolume | null>(null);
  const [gateVisualization, setGateVisualization] = useState<{ manifest: import("../../types").ResearchVisualizationManifest; densityVolume: MatlabVolume | null } | null>(null);
  const [volumeViewState, setVolumeViewState] = useState<ViewState | undefined>(undefined);
  const fileInput = useRef<HTMLInputElement>(null);
  const dropZone = useRef<HTMLDivElement>(null);
  const messageList = useRef<HTMLDivElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const uploadingHashes = useRef(new Set<string>());
  const lastEventId = useRef(0);
  const recordedAgentEvents = useRef(new Set<number>());
  const queuedSuggestionSources = useRef(new Set<string>());
  const draftsByResearch = useRef(new Map<string, ResearchDraft>());
  const selectedLoadGeneration = useRef(0);
  const selectedStatus = String(selected?.status || "").toUpperCase();
  const stoppingAutonomous = selectedStatus === "STOPPING";
  const canStopAutonomous = selectedStatus === "RUNNING" || selectedStatus === "STOP_FAILED";

  const cacheDraft = useCallback((patch: Partial<Omit<ResearchDraft, "dirty">>, dirty: Partial<ResearchDraft["dirty"]> = {}) => {
    if (!selected) return;
    const current = draftsByResearch.current.get(selected.id) || {
      goal: selected.goal || "", hypothesis: selected.hypothesis || "",
      config: researchConfig, dirty: { goal: false, hypothesis: false, config: false },
    };
    draftsByResearch.current.set(selected.id, {
      ...current, ...patch, dirty: { ...current.dirty, ...dirty },
    });
  }, [selected?.id, selected?.goal, selected?.hypothesis, researchConfig]);

  const enqueueSuggestions = useCallback((sourceId: string, actions: ResearchStateAction[], messageId: string) => {
    if (!actions.length || queuedSuggestionSources.current.has(sourceId)) return;
    queuedSuggestionSources.current.add(sourceId);
    setSuggestedActions(queue => [...queue, ...actions.map(action => ({ ...action, messageId }))]);
  }, []);
  const handleExtractedActions = useCallback((sourceId:string, actions:ResearchStateAction[], messageId:string) => {
    for (const action of actions) {
      const stateFields = action.changedFields.filter(field => field === "goal" || field === "hypothesis");
      if (stateFields.length) {
        const details = [
          stateFields.includes("goal") ? `研究目标：${action.goal || ""}` : "",
          stateFields.includes("hypothesis") ? `研究假设：${action.hypothesis || ""}` : "",
        ].filter(Boolean).join("\n\n");
        if (window.confirm(`Agent 已从方案中识别出研究目标或研究假设。是否覆盖右侧未保存内容？\n\n${details}`)) {
          if (stateFields.includes("goal") && action.goal) {
            setGoalDraft(action.goal); cacheDraft({ goal: action.goal }, { goal: true });
          }
          if (stateFields.includes("hypothesis") && action.hypothesis) {
            setHypothesisDraft(action.hypothesis); cacheDraft({ hypothesis: action.hypothesis }, { hypothesis: true });
          }
        }
      }
      if (action.changedFields.includes("optimizationConfig")) {
        enqueueSuggestions(sourceId, [{
          ...action, changedFields: ["optimizationConfig"], goal: undefined, hypothesis: undefined,
        }], messageId);
      }
    }
  }, [cacheDraft, enqueueSuggestions]);
  const metrics = useMemo(() => ({
    compliance: active?.result?.objective?.compliance,
    gray: active?.result?.quality?.gray_ratio,
    stress: active?.result?.quality?.maximum_von_mises,
    stressUnit: active?.result?.quality?.stress_unit_trusted ? "MPa" : "归一化",
  }), [active]);
  const resultView = useMemo(() => {
    const artifacts = (active?.result?.artifacts ?? {}) as Record<string, unknown>;
    // MATLAB progress publishes the full 3D cube separately from its 2D
    // mid-plane preview. Prefer the live cube for the Step4 volume viewer.
    const rawDensity = artifacts.density_3d_live ?? artifacts.density;
    const densityIs3d = Array.isArray(rawDensity) && rawDensity.length > 0
      && Array.isArray(rawDensity[0]) && Array.isArray((rawDensity[0] as unknown[])[0]);
    return {
      density: densityIs3d ? [] : normalizeResearchField(rawDensity),
      history: normalizeResearchHistory(artifacts.history),
      liveVolume: densityIs3d ? (() => {
        const cube = rawDensity as number[][][];
        return { shape: [cube.length, cube[0].length, cube[0][0].length] as [number, number, number], values: cube.flat(2) };
      })() : null,
    };
  }, [active]);
  const pendingStageGate = useMemo<ResearchStageGate | null>(() => {
    const events = selected?.events || [];
    const resolved = new Set(events.filter(event => event.title === "FIDELITY_STAGE_DECISION")
      .map(event => String(event.payload?.gate_event_id || "")));
    const gate = [...events].reverse().find(event => event.title === "FIDELITY_STAGE_AWAITING_DECISION" && !resolved.has(String(event.id)));
    if (!gate) return null;
    const payload = gate.payload || {};
    const stageCode = normalizeStep(payload.stage_code || "STEP1");
    return {
      eventId: String(gate.id), stageCode, internalFidelity: normalizeStep(payload.internal_fidelity || stageCode),
      round: Number(payload.round || 1), experimentIds: Array.isArray(payload.experiment_ids) ? payload.experiment_ids.map(String) : [],
      bestExperimentId: payload.best_experiment_id ? String(payload.best_experiment_id) : undefined,
      result: payload.result && typeof payload.result === "object" ? payload.result as Record<string, unknown> : {},
    };
  }, [selected?.events]);
  const pendingCandidatePlan = useMemo(() => {
    const workflow = ((selected?.defaults || {}).autonomous_workflow || {}) as Record<string,unknown>;
    const plan = (workflow.candidate_plan || {}) as Record<string,unknown>;
    if (plan.status !== "AWAITING_CONFIRMATION") return null;
    const ids = Array.isArray(plan.proposal_ids) ? plan.proposal_ids.map(String) : [];
    const proposals = ids.map(id => selected?.proposals?.find(item => item.id === id)).filter(Boolean) as ResearchProposal[];
    if (proposals.length !== 3) return null;
    return { proposals, recommendedProposalId:String(plan.recommended_proposal_id || ids[0]) };
  }, [selected?.defaults, selected?.proposals]);

  const persistAssistant = useCallback(async (content: string, source = "qwen", targetConversationId = conversationId) => {
    if (!targetConversationId || !content.trim()) return null;
    const saved = await api.conversationMessage(targetConversationId, { role: "assistant", content: content.trim(), source });
    setMessages(items => items.some(item => item.id === saved.id) ? items : [...items, saved]);
    if (source === "qwen") setCompletionSignal("research-reply-" + saved.id);
    return saved;
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
    const cachedDraft = draftsByResearch.current.get(selected.id);
    const initialDraft = cachedDraft || {
      goal: selected.goal || "", hypothesis: selected.hypothesis || "",
      config: DEFAULT_OPTIMIZATION_CONFIG,
      dirty: { goal: false, hypothesis: false, config: false },
    };
    draftsByResearch.current.set(selected.id, initialDraft);
    setGoalDraft(initialDraft.goal);
    setHypothesisDraft(initialDraft.hypothesis);
    setResearchConfig(initialDraft.config);
    setSuggestedActions([]);
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
      const normalizedConfig = normalizeOptimizationConfig(config);
      const currentDraft = draftsByResearch.current.get(selected.id);
      if (currentDraft?.dirty.config) {
        setResearchConfig(currentDraft.config);
      } else {
        setResearchConfig(normalizedConfig);
        draftsByResearch.current.set(selected.id, {
          ...(currentDraft || initialDraft), config: normalizedConfig,
          dirty: { ...(currentDraft || initialDraft).dirty, config: false },
        });
      }
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
  }, [selected?.id, onError]);

  useEffect(() => {
    if (!selected) return;
    const current = draftsByResearch.current.get(selected.id);
    if (!current) return;
    const next = { ...current, dirty: { ...current.dirty } };
    if (!current.dirty.goal && current.goal !== (selected.goal || "")) {
      next.goal = selected.goal || "";
      setGoalDraft(next.goal);
    }
    if (!current.dirty.hypothesis && current.hypothesis !== (selected.hypothesis || "")) {
      next.hypothesis = selected.hypothesis || "";
      setHypothesisDraft(next.hypothesis);
    }
    draftsByResearch.current.set(selected.id, next);
  }, [selected?.id, selected?.goal, selected?.hypothesis]);

  useEffect(() => {
    let cancelled = false;
    setVisualizationManifest(null);
    setDensityVolume(null);
    if (!selected || !active) return;
    void api.researchVisualization(selected.id, active.id).then(async manifest => {
      if (cancelled) return;
      setVisualizationManifest(manifest);
      if (manifest.dimension !== "3d") return;
      const density = asFortranVolume(readFloat32LittleEndian(await api.researchVisualizationField(selected.id, active.id, "density")), manifest.shape);
      if (cancelled) return;
      setDensityVolume(density);
    }).catch(() => { if (!cancelled) setVisualizationManifest(null); });
    return () => { cancelled = true; };
  }, [selected?.id, active?.id, active?.status]);
  
  useEffect(() => {
    const bestId = pendingStageGate?.bestExperimentId;
    if (!selected || !bestId) { setGateVisualization(null); return; }
    let cancelled = false;
    setGateVisualization(null);
    void api.researchVisualization(selected.id, bestId).then(async manifest => {
      if (cancelled) return;
      if (manifest.dimension !== "3d") { setGateVisualization({ manifest, densityVolume: null }); return; }
      const density = asFortranVolume(readFloat32LittleEndian(await api.researchVisualizationField(selected.id, bestId, "density")), manifest.shape);
      if (!cancelled) setGateVisualization({ manifest, densityVolume: density });
    }).catch(() => { if (!cancelled) setGateVisualization(null); });
    return () => { cancelled = true; };
  }, [selected?.id, pendingStageGate?.bestExperimentId]);

  useEffect(() => {
    if (centerTab !== "chat" || !followMessages.current) return;
    window.requestAnimationFrame(() => messageEnd.current?.scrollIntoView?.({ block: "end" }));
  }, [centerTab, messages, streamText, active?.id]);

  useEffect(() => {
    if (!DEMO_EDITION) return;
    setWorkflowProgress(selected?.workflow || null);
    const running = selected?.experiments?.find(item => ["RUNNING", "WAITING", "QUEUED"].includes(String(item.status).toUpperCase()));
    if (running) setProgressText(`实验 ${running.id} · 迭代 ${running.current_iteration || 0} · ${Math.round(Number(running.progress || 0) * 100)}%`);
  }, [selected?.workflow, selected?.experiments]);

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
          const sourceId = `event:${id}`;
          void api.researchSuggestionExtract(selected.id, sourceId, body).then(async extraction => {
            const assistant = await persistAssistant(extraction.reply || body, "pi");
            if (assistant) handleExtractedActions(sourceId, extraction.actions || [], assistant.id);
          }).catch(() => { void persistAssistant(body, "pi"); });
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

    if (DEMO_EDITION) {
      pollTimer = window.setInterval(() => {
        void api.researchEvents(selected.id, lastEventId.current).then(acceptEvents).catch(() => undefined);
        void onSelect(selected.id);
      }, 500);
      return () => {
        disposed = true;
        window.clearTimeout(refreshTimer);
        window.clearInterval(pollTimer);
      };
    }

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
            if (running) setProgressText("MATLAB / MCP 实验 " + String(running.id || "") + " · 迭代 " + String(running.current_iteration || 0) + " · " + Math.round(Number(running.progress || 0) * 100) + "%");
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
  }, [selected?.id, onSelect, onError, persistAssistant, handleExtractedActions]);

  async function autonomous() {
    if (!selected) return;
    const savedGoal = Boolean(selected.goal?.trim()) && goalDraft.trim() === selected.goal.trim();
    const savedHypothesis = Boolean(selected.hypothesis?.trim()) && hypothesisDraft.trim() === String(selected.hypothesis).trim();
    if (!savedGoal || !savedHypothesis) {
      onError("请先保存研究目标和研究假设");
      return;
    }
    setAutonomousBusy(true);
    setProgressText("正在根据研究目标制定三套候选方案");
    try { await api.autonomous(selected.id); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setAutonomousBusy(false); }
  }
  async function stopAutonomous() {
    if (!selected || stopBusy || stoppingAutonomous) return;
    setStopBusy(true);
    setProgressText("正在停止 Agent、子任务与求解器");
    try { await api.stopAutonomous(selected.id); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setStopBusy(false); }
  }
  async function confirmCandidatePlan(preferredProposalId:string) {
    if (!selected || candidatePlanBusy) return;
    setCandidatePlanBusy(true);
    try { await api.confirmResearchCandidatePlan(selected.id, preferredProposalId); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setCandidatePlanBusy(false); }
  }
  async function decideStage(action: "REPEAT_STAGE" | "ADVANCE_STAGE" | "APPROVE_FINAL", selectedExperimentId?:string) {
    if (!selected || !pendingStageGate || stageDecisionBusy) return;
    setStageDecisionBusy(true);
    try { await api.researchFidelityStageDecision(selected.id, action, selectedExperimentId); await onSelect(selected.id); }
    catch (reason) { onError(String(reason)); }
    finally { setStageDecisionBusy(false); }
  }
  async function showFinalReport() {
    if (!selected) return;
    const preview = await api.researchReportPreview(selected.id);
    setReportPreview(preview);
  }
  async function finishResearch() {
    if (!selected || finishBusy) return;
    const hasActiveWork = canStopAutonomous || Boolean(runningExperiment);
    const prompt = hasActiveWork
      ? "当前仍有研究任务运行。确认后将先停止全部任务，再结束研究并生成报告。是否继续？"
      : "确认结束当前研究并生成最终报告？未完成步骤、失败结果和缺失指标会如实保留。";
    if (!window.confirm(prompt)) return;
    setFinishBusy(true);
    try {
      let state = await api.finishResearch(selected.id);
      for (let attempt = 0; String(state.status).toUpperCase() === "STOPPING" && attempt < 120; attempt += 1) {
        await new Promise(resolve => window.setTimeout(resolve, 500));
        state = await api.getResearch(selected.id);
      }
      if (String(state.status).toUpperCase() === "STOP_FAILED") throw new Error("后台任务未能完全停止，请重试结束实验。");
      if (String(state.status).toUpperCase() === "STOPPING") throw new Error("停止任务超时，请稍后重试结束实验。");
      await onSelect(selected.id);
      await showFinalReport();
    } catch (reason) { onError(String(reason)); }
    finally { setFinishBusy(false); }
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
    if (!window.confirm("将“" + item.name + "”移入回收站？在途任务会先终止，已有科研证据和制品会保留。")) return;
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
        const reply = response.reply || (response.actions?.length ? "已生成可确认的研究状态建议。" : response.source === "not_configured" ? "当前未配置可用的 Qwen 凭据。" : "当前模型无法处理该附件，草稿已保留。");
        const assistant = await persistAssistant(reply, response.source, targetConversationId);
        if (assistant) handleExtractedActions(`message:${assistant.id}`, response.actions || [], assistant.id);
      } else if (!value.startsWith("/")) {
        setProgressText("正在读取 Research State 并生成真实回复");
        const response = await api.researchChat(selected.id, value, active?.id);
        const reply = response.reply || (response.actions?.length
          ? "已生成可确认的研究状态建议。"
          : response.source === "not_configured"
            ? "当前未配置 Qwen 凭据。科研对话已保留，但不会生成伪造回复。"
            : "当前模型不可用，科研对话已保留。");
        const assistant = await persistAssistant(reply, response.source, targetConversationId);
        if (assistant) handleExtractedActions(`message:${assistant.id}`, response.actions || [], assistant.id);
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
    try {
      const saved = await api.saveResearchGoal(selected.id, goalDraft.trim());
      const goal = saved.goal || goalDraft.trim();
      setGoalDraft(goal); cacheDraft({ goal }, { goal: false });
      await onSelect(selected.id);
    }
    catch (reason) { onError(String(reason)); }
    finally { setGoalBusy(false); }
  }

  async function saveHypothesis() {
    if (!selected || !hypothesisDraft.trim() || hypothesisDraft.trim() === (selected.hypothesis || "")) return;
    setHypothesisBusy(true);
    try {
      const saved = await api.saveResearchHypothesis(selected.id, hypothesisDraft.trim());
      const hypothesis = saved.hypothesis || hypothesisDraft.trim();
      setHypothesisDraft(hypothesis); cacheDraft({ hypothesis }, { hypothesis: false });
      await onSelect(selected.id);
    }
    catch (reason) { onError(String(reason)); }
    finally { setHypothesisBusy(false); }
  }

  async function applySuggestion(action: (ResearchStateAction & { messageId?: string }) | undefined = suggestedActions[0]) {
    if (!selected || !action) return;
    try {
      const value = await api.applyResearchSuggestion(selected.id, action);
      if (action.changedFields.includes("optimizationConfig") && value.optimizationConfig) {
        setResearchConfig(value.optimizationConfig);
        cacheDraft({ config: value.optimizationConfig }, { config: false });
      }
      if (action.changedFields.includes("goal")) {
        const goal = value.research.goal || "";
        setGoalDraft(goal); cacheDraft({ goal }, { goal: false });
      }
      if (action.changedFields.includes("hypothesis")) {
        const hypothesis = value.research.hypothesis || "";
        setHypothesisDraft(hypothesis); cacheDraft({ hypothesis }, { hypothesis: false });
      }
      setSuggestedActions(queue => queue.slice(1));
      await onSelect(selected.id);
    } catch (reason) { onError(String(reason)); }
  }

  async function saveConfig(config: OptimizationConfig, lane: EngineeringSolverLane) {
    if (!selected) return;
    try {
      const saved = await api.saveResearchOptimizationConfig(selected.id, config);
      setResearchConfig(saved);
      cacheDraft({ config: saved }, { config: false });
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
      cacheDraft({ config: value.optimizationConfig }, { config: false });
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
    </>;
  const runningExperiment = experiments.find(item => ["RUNNING", "WAITING", "QUEUED"].includes(String(item.status).toUpperCase()));
  const pendingDecision = selected?.decisions?.find(decision => decision.status === "PENDING");
  const researchStateSaved = Boolean(selected?.goal?.trim() && selected?.hypothesis?.trim()
    && goalDraft.trim() === String(selected?.goal).trim()
    && hypothesisDraft.trim() === String(selected?.hypothesis).trim());
  const stage = stoppingAutonomous ? "正在停止自主研究" : runningExperiment ? progressText : pendingDecision ? "等待 Policy 审核" : pendingStageGate ? "等待当前 Step 人工审批" : streamText ? "正在分析结果并生成回复" : autonomousBusy ? "正在制定实验方案" : "等待下一条科研指令";

  return <>
    {pendingCandidatePlan ? <CandidatePlanDialog proposals={pendingCandidatePlan.proposals} recommendedProposalId={pendingCandidatePlan.recommendedProposalId} busy={candidatePlanBusy} onConfirm={confirmCandidatePlan} onFinish={finishResearch}/> : null}
    {pendingStageGate ? <FidelityStageResultDialog gate={pendingStageGate} experiments={experiments.filter(item => pendingStageGate.experimentIds.includes(item.id))} constraints={selected?.constraints || {}} manifest={gateVisualization && gateVisualization.manifest.dimension === "3d" ? gateVisualization.manifest : null} densityVolume={gateVisualization?.densityVolume ?? null} history={active?.id === pendingStageGate.bestExperimentId ? resultView.history : []} busy={stageDecisionBusy || finishBusy} onDecision={decideStage} onFinish={finishResearch}/> : null}
    <ParameterConfigurationDialog open={configOpen} config={researchConfig} lane={researchLane} busy={Boolean(runningExperiment)} matlabDiagnostic="科研 MATLAB 任务将通过 Policy、审批和 MATLAB MCP 执行。" runtimeDiagnostic="Runtime 为可选工程链路，不替代科研审批。" onClose={() => setConfigOpen(false)} onApply={(config, lane) => void saveConfig(config, lane)}/>
    <ResearchResultDialog researchId={selected?.id || ""} experiment={resultExperiment} onClose={() => setResultExperiment(null)}/>
    {schemePickerOpen ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="engineering-scheme-import-dialog suggestion-dialog" role="dialog" aria-modal="true" aria-label="导入工程方案"><header><b>导入工程方案</b><button className="dialog-icon-button" title="关闭" aria-label="关闭工程方案导入" onClick={() => setSchemePickerOpen(false)}><X size={14}/></button></header>{engineeringSchemes.length ? <div className="engineering-scheme-import-list">{engineeringSchemes.map(item => <label className={selectedSchemeId === item.id ? "active" : ""} key={item.id}><input type="radio" name="engineering-scheme" checked={selectedSchemeId === item.id} onChange={() => setSelectedSchemeId(item.id)}/><span><b>{item.name}</b><small>Run {item.runId} · {String(item.config.dimension || "3d").toUpperCase()} · {String(item.run?.provenance.backend || item.run?.lane || "solver")}</small><small>柔度 {item.run?.metrics.compliance?.toFixed?.(4) ?? "—"} · 体积分数 {item.run?.metrics.volumeFraction?.toFixed?.(4) ?? "—"} · 灰度率 {item.run?.metrics.grayRatio?.toFixed?.(4) ?? "—"}</small></span></label>)}</div> : <p>没有完整性已验证且运行完成的工程方案。</p>}<footer><button className="outline-button" onClick={() => setSchemePickerOpen(false)}>取消</button><button className="primary-button" disabled={!selectedSchemeId || schemeImportBusy} onClick={() => void importEngineeringScheme()}>{schemeImportBusy ? "导入中…" : "导入并填入"}</button></footer></section></div> : null}
    {reportOpen ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="research-report-dialog suggestion-dialog" role="dialog" aria-modal="true" aria-label="导出科研报告"><header><b>导出科研报告</b><button className="dialog-icon-button" title="关闭" aria-label="关闭科研报告导出" onClick={() => setReportOpen(false)}><X size={14}/></button></header><label>报告名称<input maxLength={120} value={reportName} onChange={event => setReportName(event.target.value)}/></label><label>生成位置<div className="report-directory-field"><input value={reportDirectory} placeholder="输入完整目录，或点击右侧选择文件夹" onChange={event => setReportDirectory(event.target.value)}/><button className="dialog-icon-button" title="选择文件夹" aria-label="选择报告生成文件夹" onClick={() => void chooseReportDirectory()}><FolderOpen size={15}/></button></div></label><p>默认同时生成 Markdown、PDF 和配套黑白图像资源。</p><label className="report-overwrite-confirm"><input type="checkbox" checked={reportOverwrite} onChange={event => setReportOverwrite(event.target.checked)}/>覆盖同名报告和资源目录</label>{reportStatus ? <div className="report-export-status">{reportStatus}</div> : null}<footer><button className="outline-button" disabled={reportBusy} onClick={() => setReportOpen(false)}>关闭</button><button className="primary-button" disabled={reportBusy || !reportName.trim() || !reportDirectory.trim()} onClick={() => void exportResearchReport()}>{reportBusy ? <LoaderCircle className="spin" size={14}/> : null}{reportBusy ? "生成中…" : "生成报告"}</button></footer></section></div> : null}
    {reportPreview ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="research-report-preview suggestion-dialog" role="dialog" aria-modal="true" aria-label="最终科研报告"><header><b>最终科研报告</b><button className="dialog-icon-button" title="关闭" aria-label="关闭最终科研报告" onClick={() => setReportPreview(null)}><X size={14}/></button></header><small>报告依据当前 Research State 自动生成；未完成步骤和缺失指标不会被补造。</small><pre>{reportPreview.markdown}</pre><footer><button className="outline-button" onClick={() => setReportPreview(null)}>关闭</button><button className="primary-button" onClick={() => { setReportPreview(null); openReportExport(); }}>导出 Markdown/PDF</button></footer></section></div> : null}
    <ResizableWorkspaceLayout mode="deep-optimization"
      activitySignal={runningExperiment ? "research-" + (selected?.id || "none") + "-" + runningExperiment.id : autonomousBusy ? "research-planning-" + (selected?.id || "none") : ""}
      completionSignal={completionSignal}
      leftRail={<div className="left-rail-icons"><button aria-label="研究项目" title="研究项目"><FlaskConical size={15}/></button><button aria-label="科研对话" title="科研对话" onClick={() => setCenterTab("chat")}><MessageCircle size={15}/></button><button aria-label="科研审批" title="科研审批" onClick={() => setCenterTab("audit")}><ShieldCheck size={15}/></button></div>}
      left={leftPane}
      center={<section className="v2-center research-center research-chat-workspace">
        <div className="research-header"><div><h1>{selected?.name || "选择一个 Research"}</h1></div><div className="research-header-actions"><button className="outline-button" disabled={!selected || finishBusy || stoppingAutonomous} onClick={() => void finishResearch()}>{finishBusy ? <LoaderCircle className="spin" size={14}/> : <Square size={13}/>} {finishBusy ? "正在结束…" : "结束实验"}</button><button className="primary-button" data-unsaved-research-state={Boolean(selected) && !researchStateSaved ? "true" : undefined} title={Boolean(selected) && !researchStateSaved ? "请先保存研究目标和研究假设" : undefined} disabled={!selected || autonomousBusy || stopBusy || stoppingAutonomous || Boolean(pendingCandidatePlan) || (!canStopAutonomous && (Boolean(runningExperiment) || Boolean(pendingStageGate)))} onClick={() => void (canStopAutonomous ? stopAutonomous() : autonomous())}>{stoppingAutonomous || stopBusy ? <LoaderCircle className="spin"/> : canStopAutonomous ? <Square size={13}/> : <Play size={14}/>} {stoppingAutonomous || stopBusy ? "正在停止…" : canStopAutonomous ? "停止自主研究" : "运行自主研究"}</button></div></div>
        <nav className="v2-tabs research-center-tabs" role="tablist"><button role="tab" aria-selected={centerTab === "chat"} className={"tab" + (centerTab === "chat" ? " active" : "")} onClick={() => setCenterTab("chat")}><MessageCircle size={14}/>科研对话</button><button role="tab" aria-selected={centerTab === "audit"} className={"tab" + (centerTab === "audit" ? " active" : "")} onClick={() => setCenterTab("audit")}><ShieldCheck size={14}/>过程 / 审计</button></nav>
        <div className="research-stage-strip"><span className="connection-dot"/><b>{stage}</b><small>{agentEvent}</small></div>
        {workflowProgress && workflowProgress.stage !== "idle" ? <section className="research-workflow-progress" aria-label="自主研究阶段进度"><header><b>第 {workflowProgress.round} 轮</b><span>{workflowProgress.percent}%</span></header><div className="research-workflow-track"><i style={{ width: `${workflowProgress.percent}%` }}/></div><small>{workflowProgress.steps.find(item => item.status === "active")?.label || (workflowProgress.percent === 100 ? "本轮已完成" : "等待下一阶段")}</small></section> : null}
        {centerTab === "chat" ? <div ref={dropZone} className={"research-chat-main chat-drop-zone" + (dragActive ? " drag-active" : "")} {...dropHandlers}>
          {dragActive ? <div className="chat-drop-overlay"><ImagePlus size={20}/><b>松开以上传附件</b><span>图片、PDF、Word、Excel、SVG、文本 · 单个不超过 10 MB</span></div> : null}
          <div ref={messageList} className="chat-message-list research-message-list" onScroll={() => { const node = messageList.current; if (node) followMessages.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80; }}>{messages.map(item => <article className={"chat-message " + item.role} key={item.id}><span className="chat-avatar">{item.role === "assistant" ? <Bot size={14}/> : "你"}</span><div><p>{item.content}</p>{item.attachments?.length ? <small>{item.attachments.length} 个附件 · 已保存在该 Research 会话</small> : null}{item.source ? <small>{item.source}</small> : null}</div></article>)}{streamText ? <article className="chat-message assistant streaming"><span className="chat-avatar"><Bot size={14}/></span><div><p>{streamText}</p><small>Pi / Qwen 正在生成真实回复…</small></div></article> : null}{!messages.length && !streamText ? <div className="chat-empty"><Bot size={28}/><b>直接描述研究目标或下一项实验</b><span>AI 会读取 Research State；Step1–Step3 每轮运行三个不同方向候选，Step4 运行一个 MATLAB 验证实验，结束后均等待人工决定。</span></div> : null}{active ? <section className="research-result-panel"><header><span>当前优化结果 · {active.id}</span><small>{stepLabel(active.fidelity)} · {active.backend} · {active.status}</small></header><div className="result-plots"><section><h4 className="field-heading"><span>密度场</span></h4>{(visualizationManifest?.dimension === "3d" && densityVolume) || resultView.liveVolume ? <InteractiveVolumeView density={resultView.liveVolume ?? densityVolume!} field={resultView.liveVolume ?? densityVolume!} mode="density" viewState={volumeViewState} onViewStateChange={setVolumeViewState} surfaceOnly/> : <ScalarMap values={resultView.density} mode="density"/>}</section><section className="convergence-pane"><h4>柔度收敛</h4><ConvergenceChart points={resultView.history}/></section></div></section> : null}<div ref={messageEnd} className="chat-message-end" aria-hidden="true"/></div>
          {suggestedActions[0] ? <ResearchSuggestionCard action={suggestedActions[0]} currentGoal={selected?.goal || ""} currentHypothesis={selected?.hypothesis || ""} currentConfig={researchConfig} onApply={(action) => void applySuggestion(action)} onCancel={() => setSuggestedActions(queue => queue.slice(1))} /> : null}
          <footer className="chat-composer research-chat-composer">{attachments.length ? <div className="chat-attachment-preview">{attachments.map(item => <figure key={item.id}>{item.preview ? <img src={item.preview} alt={item.fileName || "待发送附件"}/> : <span className="attachment-file-name">{item.fileName || "附件"}</span>}<button aria-label="移除附件" onClick={() => setAttachments(values => values.filter(value => value.id !== item.id))}><X size={12}/></button></figure>)}</div> : null}<div><button type="button" className="chat-composer-action scheme-import-button" aria-label="导入工程方案" title="导入工程方案" onClick={() => void openSchemePicker()} disabled={!selected || sending || schemeImportBusy}><Plus size={15}/></button><input ref={fileInput} hidden type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf,.docx,.xlsx,.txt,.md,.csv" multiple onChange={event => void uploadFiles(event.target.files)}/><button type="button" className="chat-composer-action" aria-label="上传科研附件" title="上传附件" onClick={() => fileInput.current?.click()} disabled={sending}><ImagePlus size={15}/></button><textarea value={command} onChange={event => setCommand(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendResearchMessage(); } }} placeholder="描述目标、询问证据或提出下一项实验…"/><button className="chat-composer-action" aria-label="发送科研消息" title="发送" onClick={() => void sendResearchMessage()} disabled={(!command.trim() && !attachments.length) || sending || busy}>{sending || busy ? <LoaderCircle className="spin" size={15}/> : <Send size={15}/>}</button></div></footer>
        </div> : <div className="research-audit-main">{selected?.events?.slice(-30).map(event => <article className="timeline-item" key={event.id}><span className="timeline-icon"><CheckCircle2 size={14}/></span><div><small>{event.kind} · {new Date(event.created_at).toLocaleTimeString()}</small><h3>{event.title}</h3><p>{event.body}</p></div></article>)}{selected?.decisions?.filter(decision => decision.status === "PENDING").map(decision => <article className="decision-card" key={decision.id}><header><ShieldCheck size={14}/>Policy 审批 <span>{decision.risk}</span></header><h3>{decision.proposal?.fidelity || "实验提案"}</h3><p>{decision.reason}</p><div><button className="approve" onClick={() => onDecision(decision.id, "approve")}>批准并提交</button><button onClick={() => onDecision(decision.id, "reject")}>拒绝</button></div></article>)}</div>}
      </section>}
      bottom={<section className="research-bottom-progress"><header><b>科研执行进度</b><span>{workflowProgress ? `第 ${workflowProgress.round} 轮 · ${workflowProgress.percent}%` : stage}</span></header><div className="research-workflow-steps">{(workflowProgress?.steps || []).map(step => <article className={"research-workflow-step " + step.status} key={step.id}><header><span className="workflow-step-state"/><b>{step.label}</b><small>{step.status === "completed" ? "已完成" : step.status === "active" ? "进行中" : step.status === "failed" ? "失败" : "等待"}</small></header>{step.result ? <p><strong>结果</strong>{step.result}</p> : null}{step.reflection ? <p><strong>反思</strong>{step.reflection}</p> : null}{step.id !== "context" && step.evidenceIds.length ? <p><strong>证据</strong>{step.evidenceIds.join(" · ")}</p> : null}{step.nextAction ? <p><strong>下一步</strong>{step.nextAction}</p> : null}</article>)}{!workflowProgress ? <div className="research-progress-empty">尚未启动 Step1。</div> : null}</div></section>}
      right={<>
        <div className="v2-pane-title"><span>研究状态</span><span className="permission research">research</span></div>
        {selected ? <>
          <section className="inspector-card research-goal-card">
            <h4 className="research-state-heading">研究目标</h4>
            <textarea aria-label="研究目标" placeholder="填写希望达成的科研目标" value={goalDraft} onChange={event => { setGoalDraft(event.target.value); cacheDraft({ goal: event.target.value }, { goal: true }); }} maxLength={2000}/>
            <button className="primary-button" disabled={goalBusy || !goalDraft.trim() || goalDraft.trim() === selected.goal} onClick={() => void saveGoal()}>{goalBusy ? "保存中…" : "保存目标"}</button>
          </section>
          <section className="inspector-card research-hypothesis-card">
            <h4 className="research-state-heading">研究假设</h4>
            <textarea aria-label="研究假设" placeholder="填写待验证的机制、趋势或因果假设" value={hypothesisDraft} onChange={event => { setHypothesisDraft(event.target.value); cacheDraft({ hypothesis: event.target.value }, { hypothesis: true }); }} maxLength={4000}/>
            <button className="primary-button" disabled={hypothesisBusy || !hypothesisDraft.trim() || hypothesisDraft.trim() === (selected.hypothesis || "")} onClick={() => void saveHypothesis()}>{hypothesisBusy ? "保存中…" : "保存假设"}</button>
          </section>
          <section className="inspector-card engineering-settings-card parameter-summary-card research-config-card" aria-label="参数配置">
            <header><div><h4 className="research-state-heading">参数配置</h4></div><button aria-label="打开参数配置" title="打开完整参数配置" onClick={() => setConfigOpen(true)}><Settings2 size={15}/></button></header>
            <dl>
              <div><dt>求解维度</dt><dd>{researchConfig.dimension.toUpperCase()}</dd></div>
              <div><dt>网格</dt><dd>{researchConfig.nelx} × {researchConfig.nely}{researchConfig.dimension === "3d" ? " × " + researchConfig.nelz : ""}</dd></div>
              <div><dt>工况</dt><dd>{researchConfig.bcType}</dd></div>
              <div><dt>体积分数</dt><dd>{researchConfig.volfrac}</dd></div>
              <div><dt>材料</dt><dd>{researchConfig.material.name}</dd></div>
              <div><dt>求解链路</dt><dd>{solverLaneLabel(researchLane)}</dd></div>
            </dl>
            <button className="primary-button open-parameter-dialog" onClick={() => setConfigOpen(true)}><Settings2 size={14}/>打开详细参数</button>
          </section>
          <section className="inspector-card research-results-card">
            <h4 className="research-state-heading">结果呈现</h4>
            {active ? <><div className="run-heading"><div><h3>{active.id}</h3><small>{active.fidelity} · {active.backend}</small></div><span className={"status status-" + active.status.toLowerCase()}>{active.status}</span></div><div className="metric-cards"><Metric label="柔度" value={metrics.compliance}/><Metric label="灰度率" value={metrics.gray}/><Metric label={`最大应力（${metrics.stressUnit}）`} value={metrics.stress}/></div>{active.error ? <p className="error-text">{active.error}</p> : null}</> : <p className="inspector-empty-copy">尚无科研实验结果。</p>}
          <div className="research-plan-flow" aria-label="四步深度优化流程">{([["STEP1", "Step1 · Python 粗网格 2D"], ["STEP2", "Step2 · Python 自适应粗网格 2D"], ["STEP3", "Step3 · Python 粗网格 3D"], ["STEP4", "Step4 · MATLAB 真实网格 3D"]] as Array<[string, string]>).map(([code, label]) => <span key={code} className={normalizeStep(runningExperiment?.fidelity || active?.fidelity || "STEP1") === code ? "active" : ""}>{label}</span>)}</div>
            <div className="research-artifact-list">{artifactIndex.experiments.slice(-5).map(item => <div className="artifact-row" key={item.experimentId}><span><FileJson2 size={12}/>{item.experimentId} · {item.backend}</span><small>{item.files.length} 个文件 · {item.provenance.resultKind || "unknown"}</small></div>)}</div>
            {experiments.length ? <div className="research-result-experiments"><h5>实验</h5><div className="research-experiment-scroll">{experiments.map(experiment => <div className="experiment-row-shell" key={experiment.id}><button className={"experiment-row " + (active?.id === experiment.id ? "active" : "")} onClick={() => onSelectExperiment(experiment)}><span className="experiment-status"/><span>{experiment.id}<small>{solverLaneLabel(experiment.backend === "matlab" ? "matlab-mcp" : "python-fem")} · {experiment.fidelity}</small></span></button></div>)}</div></div> : null}
            <button className="primary-button research-final-result-button" disabled={!selected?.best_experiment} title={selected?.best_experiment ? "查看最终方案" : "尚无真实最终方案"} onClick={() => setResultExperiment(selected?.best_experiment || null)}>查看最终方案</button>
            <div className="inspector-actions artifact-actions"><button className="outline-button" onClick={() => void pareto()}>查看 Pareto</button><button className="outline-button" disabled={experiments.length < 2} onClick={() => void compare()}>比较实验</button><button className="outline-button" onClick={openReportExport}>生成报告</button><button className="outline-button" onClick={() => void createResearchArtifact("/export")}>复现包</button></div>
          </section>
        </> : <div className="inspector-empty"><FlaskConical size={24}/><span>选择或新建 Research</span></div>}
      </>}
    />
  </>;
}

function CandidatePlanDialog({proposals,recommendedProposalId,busy,onConfirm,onFinish}:{proposals:ResearchProposal[];recommendedProposalId:string;busy:boolean;onConfirm:(id:string)=>void;onFinish:()=>void}) {
  const [selectedId,setSelectedId]=useState(recommendedProposalId);
  useEffect(()=>setSelectedId(recommendedProposalId),[recommendedProposalId]);
  return <div className="suggestion-dialog-backdrop" role="presentation"><section className="research-suggestion-card suggestion-dialog candidate-plan-dialog" role="dialog" aria-modal="true" aria-label="Step1 候选方案"><header><b>Step1 · 三候选方案</b><span>求解前确认</span></header><p>以下方案均已通过 Policy 编译，但尚未运行 FEM。“Agent 推荐”只表示规划偏好，不代表实验最优。</p><div className="candidate-plan-list">{proposals.map((proposal,index)=>{const params=proposal.parameters||{};const grid=Array.isArray(params.grid3d)?params.grid3d.join("×"):"—";return <label key={proposal.id} className={selectedId===proposal.id?"active":""}><input type="radio" name="step1-candidate" checked={selectedId===proposal.id} onChange={()=>setSelectedId(proposal.id)}/><span><b>方案 {index+1}{proposal.id===recommendedProposalId?<em>Agent 推荐</em>:null}</b><small>{proposal.purpose}</small><small>研究方向：{proposal.intent} · 受控因素：{proposal.controlled_factors?.join("、")||"基线"}</small><small>网格 {grid} · β {String(params.beta??"—")}→{String(params.beta_max??params.beta??"—")} · move {String(params.move??"—")}</small>{proposal.evidence_source?<small>证据：{proposal.evidence_source}</small>:null}<small>风险：{proposal.risk} · 后端：{proposal.backend}</small></span></label>})}</div><footer><button className="outline-button" disabled={busy} onClick={onFinish}>结束实验并生成报告</button><button className="primary-button" disabled={busy||!selectedId} onClick={()=>onConfirm(selectedId)}>{busy?<LoaderCircle className="spin" size={14}/>:null}确认偏好并运行全部三方案</button></footer></section></div>;
}

function FidelityStageResultDialog({ gate, experiments, constraints, manifest, densityVolume, history, busy, onDecision, onFinish }: { gate: ResearchStageGate; experiments:Experiment[]; constraints:Record<string,unknown>; manifest:import("../../types").ResearchVisualizationManifest|null; densityVolume:MatlabVolume|null; history:Array<{iteration:number;compliance:number}>; busy:boolean; onDecision:(action:"REPEAT_STAGE"|"ADVANCE_STAGE"|"APPROVE_FINAL",selectedExperimentId?:string)=>void; onFinish:()=>void }) {
  const failed = Number(gate.result.failed || 0);
  const compliance = gate.result.best_compliance;
  const weakPoints = Array.isArray(gate.result.weak_points) ? gate.result.weak_points.map(String) : [];
  const finalStage = gate.stageCode === "STEP4";
  const comparisonStage = experiments.length > 1;
  const recommended = experiments.find(item=>item.id===gate.bestExperimentId)||null;
  const [selectedId,setSelectedId]=useState(gate.bestExperimentId||"");
  useEffect(()=>setSelectedId(gate.bestExperimentId||""),[gate.eventId,gate.bestExperimentId]);
  const selectedExperiment=experiments.find(item=>item.id===selectedId)||null;
  const artifacts = (recommended?.result?.artifacts || {}) as Record<string,unknown>;
  const density2d = normalizeResearchField(artifacts.density);
  const volume = recommended?.result?.constraints?.volume_fraction;
  const gray = recommended?.result?.quality?.gray_ratio;
  const connected = recommended?.result?.quality?.connected_components;
  const targetVolume = constraints.volume_fraction ?? constraints.volfrac;
  const targetGray = constraints.gray_max;
  const usable = Boolean(selectedExperiment && selectedExperiment.status==="SUCCESS" && typeof selectedExperiment.result?.objective?.compliance==="number");
  return <div className="suggestion-dialog-backdrop" role="presentation"><section className={"research-suggestion-card suggestion-dialog fidelity-stage-dialog" + (manifest?.dimension === "3d" ? " fidelity-stage-wide" : "")} role="dialog" aria-modal="true" aria-label={`${stepLabel(gate.stageCode)} 阶段结果`}>
    <header><b>{stepLabel(gate.stageCode)} 阶段结果</b><span>第 {gate.round} 轮</span></header>
    <p>{finalStage ? "Step4 MATLAB 真实网格 3D 已完成。指标只用于审查，是否结束由你决定。" : comparisonStage ? "本轮三个候选均已到达终态。确定性评估器给出推荐方案，你也可以选择其他具有可用真实结果的方案作为下一 Step 基线。" : "本轮受控方案已到达终态。请审查结果后决定重复当前 Step 或进入下一 Step。"}</p>
    <div className="stage-candidate-results">{experiments.map(item=>{const itemCompliance=item.result?.objective?.compliance;const itemUsable=item.status==="SUCCESS"&&typeof itemCompliance==="number";return <label key={item.id} className={(selectedId===item.id?"active ":"")+(item.id===gate.bestExperimentId?"recommended":"")}><input type="radio" name="stage-result-candidate" disabled={!itemUsable||finalStage||!comparisonStage} checked={selectedId===item.id} onChange={()=>setSelectedId(item.id)}/><span><b>{item.id}{item.id===gate.bestExperimentId?<em>{comparisonStage?"评估器推荐":"本轮结果"}</em>:null}</b><small>{item.status} · 柔度 {typeof itemCompliance==="number"?itemCompliance.toFixed(4):"不可用"}</small><small>灰度率 {typeof item.result?.quality?.gray_ratio==="number"?item.result.quality.gray_ratio.toFixed(4):"不可用"} · 连通分量 {item.result?.quality?.connected_components??"不可用"}</small>{item.error?<small className="error-text">{item.error}</small>:null}</span></label>})}</div>
    <div className="stage-result-summary"><b>{comparisonStage?"确定性评估器推荐":"本轮受控结果"}</b><span>{gate.bestExperimentId || `无可用结果（${failed} 次失败）`}</span><strong>{typeof compliance === "number" ? `柔度 ${compliance.toFixed(4)}` : "柔度不可用"}</strong></div>
    {recommended?.result ? <><div className="stage-result-visuals"><section><h4>{comparisonStage?"推荐方案拓扑":"本轮结果拓扑"}</h4>{manifest?.dimension === "3d" && densityVolume ? <InteractiveVolumeView density={densityVolume} field={densityVolume} mode="density" surfaceOnly/> : <ScalarMap values={density2d} mode="density"/>}</section><section className="convergence-pane"><h4>柔度收敛</h4><ConvergenceChart points={history.length ? history : normalizeResearchHistory(artifacts.history)}/></section></div><div className="stage-target-comparison"><MetricCompare label="体积分数" current={volume} target={targetVolume}/><MetricCompare label="灰度率" current={gray} target={targetGray}/><MetricCompare label="连通分量" current={connected} target={constraints.connected === true ? 1 : undefined}/><MetricCompare label="柔度" current={compliance} target={constraints.compliance_target}/></div></> : <div className="error-card">本轮没有可审查的有效制品。你仍可重复当前 Step 或结束研究。</div>}
    {weakPoints.length ? <div className="stage-diagnosis"><b>当前诊断</b><span>{weakPoints.join("；")}</span></div> : null}
    <footer><button className="outline-button" disabled={busy} onClick={() => onDecision("REPEAT_STAGE")}>{finalStage?"继续 Step4 一轮":comparisonStage?"重新生成三套对比方案":"重复当前 Step"}</button><button className="outline-button" disabled={busy} onClick={onFinish}>{busy?<LoaderCircle className="spin" size={14}/>:null}结束实验并生成报告</button>{!finalStage?<button className="primary-button" disabled={busy||!usable} title={!usable?"当前没有可用真实结果":""} onClick={()=>onDecision("ADVANCE_STAGE",selectedId)}>{comparisonStage?"以所选方案进入下一 Step":"确认结果并进入下一 Step"}</button>:null}</footer>
  </section></div>;
}

function MetricCompare({label,current,target}:{label:string;current:unknown;target:unknown}) {
  const shownValue=(value:unknown)=>typeof value === "number" ? value.toFixed(4) : value === undefined || value === null ? "未设定目标值" : String(value);
  return <div><small>{label}</small><b>{shownValue(current)}</b><span>目标：{shownValue(target)}</span></div>;
}

function ResearchSuggestionCard({ action, currentGoal, currentHypothesis, currentConfig, onApply, onCancel }: {
  action: ResearchStateAction & { messageId: string }; currentGoal: string; currentHypothesis: string; currentConfig: OptimizationConfig;
  onApply: (action: ResearchStateAction) => void; onCancel: () => void;
}) {
  const [goal, setGoal] = useState(action.goal || currentGoal);
  const [hypothesis, setHypothesis] = useState(action.hypothesis || currentHypothesis);
  const [config, setConfig] = useState(action.optimizationConfig || currentConfig);
  const [editorOpen, setEditorOpen] = useState(false);
  useEffect(() => {
    setGoal(action.goal || currentGoal);
    setHypothesis(action.hypothesis || currentHypothesis);
    setConfig(action.optimizationConfig || currentConfig);
    setEditorOpen(false);
  }, [action.messageId, action.goal, action.hypothesis, action.optimizationConfig, currentGoal, currentHypothesis, currentConfig]);
  const rows = action.changedFields.map(field => {
    if (field === "goal") return { label: "研究目标", current: currentGoal || "未填写", next: goal || "—" };
    if (field === "hypothesis") return { label: "研究假设", current: currentHypothesis || "未填写", next: hypothesis || "—" };
    const current = currentConfig.dimension.toUpperCase() + " · " + currentConfig.nelx + "×" + currentConfig.nely + "×" + currentConfig.nelz + " · volfrac " + currentConfig.volfrac;
    const next = config.dimension.toUpperCase() + " · " + config.nelx + "×" + config.nely + "×" + config.nelz + " · volfrac " + config.volfrac;
    return { label: "参数配置", current, next };
  });
  const submitted: ResearchStateAction = {
    type: "apply_research_state",
    messageId: action.messageId,
    goal: action.changedFields.includes("goal") ? goal.trim() : undefined,
    hypothesis: action.changedFields.includes("hypothesis") ? hypothesis.trim() : undefined,
    optimizationConfig: action.changedFields.includes("optimizationConfig") ? config : undefined,
    changedFields: action.changedFields,
    rationale: action.rationale,
  };
  return <><div className="suggestion-dialog-backdrop" role="presentation"><section className="research-suggestion-card suggestion-dialog" role="dialog" aria-modal="true" aria-label="Agent 研究状态建议"><header><b>Agent 研究状态建议</b><button className="dialog-icon-button" aria-label="取消研究建议" title="取消" onClick={onCancel}><X size={14}/></button></header>{action.rationale ? <p>{action.rationale}</p> : null}<div>{rows.map(row => <article key={row.label}><b>{row.label}</b><span>{row.current}</span><i>→</i><strong>{row.next}</strong></article>)}</div>{action.changedFields.includes("goal") ? <label>建议研究目标<textarea value={goal} onChange={event => setGoal(event.target.value)} /></label> : null}{action.changedFields.includes("hypothesis") ? <label>建议研究假设<textarea value={hypothesis} onChange={event => setHypothesis(event.target.value)} /></label> : null}{action.changedFields.includes("optimizationConfig") ? <button className="outline-button suggestion-edit-config" onClick={() => setEditorOpen(true)}>编辑建议参数</button> : null}<footer><button className="outline-button" onClick={onCancel}>取消</button><button className="primary-button" disabled={(action.changedFields.includes("goal") && !goal.trim()) || (action.changedFields.includes("hypothesis") && !hypothesis.trim())} onClick={() => onApply(submitted)}>批准并填入</button></footer></section></div><ParameterConfigurationDialog open={editorOpen} config={config} lane="local-matlab" busy={false} matlabDiagnostic="建议参数编辑" runtimeDiagnostic="建议参数编辑" onClose={() => setEditorOpen(false)} onApply={(next) => { setConfig(next); setEditorOpen(false); }} /></>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  return <div><small>{label}</small><b>{typeof value === "number" ? value.toFixed(3) : String(value ?? "—")}</b></div>;
}
