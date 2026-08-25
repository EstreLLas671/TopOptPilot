import { useEffect, useMemo, useState } from "react";
import { ArchiveRestore, Bot, CheckCircle2, ChevronRight, FileJson2, FlaskConical, LoaderCircle, Play, Send, ShieldCheck, SquareTerminal, Trash2 } from "lucide-react";
import { api } from "../../api";
import type { Experiment, Research } from "../../types";
import { solverLaneLabel } from "../../workspace";
import { ConvergenceChart, ScalarMap } from "../engineering/ResultViewer";
import { normalizeResearchField, normalizeResearchHistory } from "./research-result";
import ResizableWorkspaceLayout from "../../components/ResizableWorkspaceLayout";

type ArtifactIndex = { experiments: Array<{ experimentId: string; status: string; fidelity: string; backend: string; provenance: Record<string, string>; files: Array<{ relativePath: string; sizeBytes: number; sha256: string }>; metrics: Record<string, number | null> }> };
type Props = {
  researches: Research[];
  selected: Research | null;
  active?: Experiment;
  command: string;
  busy: boolean;
  safeMode: boolean;
  onCommand: () => void;
  onCreateResearch: () => void;
  onArchive: (id: string) => Promise<void>;
  onRestore: (id: string) => Promise<void>;
  onDecision: (id: string, action: "approve" | "reject") => void;
  onError: (message: string) => void;
  onSelect: (id: string) => Promise<void>;
  onSelectExperiment: (experiment: Experiment) => void;
  setCommand: (value: string) => void;
};

export default function ResearchWorkspace(props: Props) {
  const { researches, selected, active, command, busy, safeMode, onCommand, onCreateResearch, onArchive, onRestore, onDecision, onError, onSelect, onSelectExperiment, setCommand } = props;
  const experiments = selected?.experiments ?? [];
  const [artifactIndex, setArtifactIndex] = useState<ArtifactIndex>({ experiments: [] });
  const [agentEvent, setAgentEvent] = useState("等待 Research 事件");
  const [autonomousBusy, setAutonomousBusy] = useState(false);
  const [trashOpen, setTrashOpen] = useState(false);
  const [archived, setArchived] = useState<Research[]>([]);
  const metrics = useMemo(() => ({ compliance: active?.result?.objective?.compliance, gray: active?.result?.quality?.gray_ratio }), [active]);
  const resultView = useMemo(() => {
    const artifacts = (active?.result?.artifacts ?? {}) as Record<string, unknown>;
    return { density: normalizeResearchField(artifacts.density), history: normalizeResearchHistory(artifacts.history) };
  }, [active]);


  useEffect(() => {
    if (!selected) { setArtifactIndex({ experiments: [] }); return; }
    let cancelled = false;
    api.researchArtifacts(selected.id).then(value => { if (!cancelled) setArtifactIndex(value); }).catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [selected?.id, selected?.experiments.length, onError]);
  useEffect(() => {
    if (!selected) return;
    let disposed = false;
    let socket: WebSocket | null = null;
    let refreshTimer = 0;
    void api.stream(selected.id).then(value => {
      if (disposed) { value.close(); return; }
      socket = value;
      socket.onmessage = event => {
        try {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          setAgentEvent(String(payload.type || payload.kind || "research-event"));
          window.clearTimeout(refreshTimer);
          refreshTimer = window.setTimeout(() => void onSelect(selected.id), 180);
        } catch { setAgentEvent("收到无法解析的 Research 事件"); }
      };
      socket.onerror = () => setAgentEvent("Research 实时流暂不可用；权威状态仍从 Research State 刷新");
    }).catch(reason => {
      if (!disposed) {
        setAgentEvent("Research 实时流连接失败；权威状态仍从 Research State 刷新");
        onError(String(reason));
      }
    });
    return () => {
      disposed = true;
      window.clearTimeout(refreshTimer);
      socket?.close();
    };
  }, [selected?.id, onSelect, onError]);

  async function autonomous() {
    if (!selected) return;
    setAutonomousBusy(true);
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
    try { const value = await api.researchPareto(selected.id); window.alert(`真实 Pareto 候选：${value.length} 个`); }
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


  async function toggleTrash() {
    const next = !trashOpen;
    setTrashOpen(next);
    if (!next) return;
    try { setArchived(await api.listResearch(true)); }
    catch (reason) { onError(String(reason)); }
  }
  async function archive(item: Research) {
    if (!window.confirm("将“" + item.name + "”移入回收站？科研证据和制品会保留。")) return;
    await onArchive(item.id);
    try { setArchived(await api.listResearch(true)); }
    catch (reason) { onError(String(reason)); }
  }
  async function restore(item: Research) {
    await onRestore(item.id);
    setArchived(items => items.filter(value => value.id !== item.id));
  }

  const leftPane = <><div className="v2-pane-title"><span>{trashOpen ? "回收站" : "Research"}</span><span className="count">{trashOpen ? archived.length : researches.length}</span><div className="research-list-actions"><button aria-label={trashOpen ? "返回 Research 列表" : "打开 Research 回收站"} title={trashOpen ? "返回 Research 列表" : "回收站"} onClick={() => void toggleTrash()}>{trashOpen ? <ChevronRight size={13}/> : <Trash2 size={13}/>}</button>{!trashOpen ? <button className="primary-button compact" onClick={onCreateResearch}><FlaskConical size={13}/>新建</button> : null}</div></div>
    <div className="research-list">{(trashOpen ? archived : researches).map(item => <div className={"research-row-shell " + (selected?.id === item.id && !trashOpen ? "active" : "")} key={item.id}><button className="research-row research-select" disabled={trashOpen} onClick={() => void onSelect(item.id)}><FlaskConical size={15}/><span><b>{item.name}</b><small>{item.status} · {item.id}</small></span><ChevronRight size={14}/></button><button className="research-row-action" aria-label={(trashOpen ? "恢复" : "删除") + item.name} title={trashOpen ? "恢复 Research" : "移入回收站"} onClick={() => void (trashOpen ? restore(item) : archive(item))}>{trashOpen ? <ArchiveRestore size={14}/> : <Trash2 size={14}/>}</button></div>)}</div>
    {!((trashOpen ? archived : researches).length) ? <div className="research-list-empty">{trashOpen ? "回收站为空" : "尚无 Research"}</div> : null}
    <div className="research-evidence"><h4>证据索引</h4><p>Research State 是唯一权威来源。移入回收站不会删除实验、审批、报告或制品。</p><div className="budget-line"><span>预算</span><b>{selected?.budget_used ?? 0}/{selected?.budget_total ?? 0}</b></div></div></>;
  const runningExperiment = experiments.find(item => ["RUNNING", "QUEUED"].includes(String(item.status).toUpperCase()));

  return <ResizableWorkspaceLayout mode="research"
    activitySignal={runningExperiment ? `research-${selected?.id || "none"}-${runningExperiment.id}` : ""}
    leftRail={<div className="left-rail-icons"><button aria-label="研究项目" title="研究项目"><FlaskConical size={15}/></button><button aria-label="实验与证据" title="实验与证据"><FileJson2 size={15}/></button><button aria-label="科研审批" title="科研审批"><ShieldCheck size={15}/></button></div>}
    left={leftPane}
    center={<section className="v2-center research-center"><div className="research-header"><div><span className="eyebrow">AI SCIENTIST WORKSPACE</span><h1>{selected?.name || "选择一个 Research"}</h1><p>{selected?.goal || "研究时间线、审批卡与可复现实验制品"}</p></div><div className="research-header-actions"><span className={`agent-mode ${safeMode ? "safe" : "online"}`}>{safeMode ? "规则 Safe Mode" : "Pi / Qwen"}</span><button className="primary-button" disabled={!selected || autonomousBusy} onClick={() => void autonomous()}>{autonomousBusy ? <LoaderCircle className="spin"/> : <Play size={14}/>}运行自主研究</button></div></div>
      <div className="stream-strip"><i className="connection-dot"/>{agentEvent}</div>
      <div className="timeline">{selected?.events?.slice(-12).map(event => <article className="timeline-item" key={event.id}><span className="timeline-icon"><CheckCircle2 size={14}/></span><div><small>{event.kind} · {new Date(event.created_at).toLocaleTimeString()}</small><h3>{event.title}</h3><p>{event.body}</p></div></article>)}{!selected?.events?.length ? <div className="v2-empty"><Bot size={28}/><p>暂无研究事件</p></div> : null}</div>
      {active ? <section className="research-result-panel">
        <header><span>统一结果查看器 · {active.id}</span><small>{active.fidelity} · {active.backend} · {active.status}</small></header>
        <div className="result-plots"><section><h4>密度场</h4><ScalarMap values={resultView.density} mode="density"/></section>
          <section><h4>柔度收敛</h4><ConvergenceChart points={resultView.history}/></section></div>
      </section> : null}
      {selected?.decisions?.filter(decision => decision.status === "PENDING").map(decision => <article className="decision-card" key={decision.id}><header><ShieldCheck size={14}/>Policy 审批 <span>{decision.risk}</span></header><h3>{decision.proposal?.fidelity || "实验提案"}</h3><p>{decision.reason}</p><div><button className="approve" onClick={() => onDecision(decision.id, "approve")}>批准并提交</button><button onClick={() => onDecision(decision.id, "reject")}>拒绝</button></div></article>)}
    </section>}
    bottom={<>
      <div className="research-composer"><SquareTerminal size={16}/><input value={command} onChange={event => setCommand(event.target.value)} onKeyDown={event => { if (event.key === "Enter") onCommand(); }} placeholder="向科研 Agent 提出下一步问题…"/><button onClick={onCommand} disabled={!command.trim() || busy}>{busy ? <LoaderCircle className="spin"/> : <Send size={15}/>}</button></div>
    </>}
    right={<><div className="v2-pane-title"><span>科研 Agent</span><span className="permission research">research</span></div>{active ? <><section className="inspector-card"><div className="run-heading"><div><h3>{active.id}</h3><small>{active.fidelity}</small></div><span className={`status status-${active.status.toLowerCase()}`}>{active.status}</span></div><div className="metric-cards"><Metric label="compliance" value={metrics.compliance}/><Metric label="gray ratio" value={metrics.gray}/><Metric label="backend" value={active.backend}/></div></section><section className="inspector-card"><h4>执行边界</h4><div className="policy-row"><ShieldCheck size={14}/>Policy 审批链 <b>受保护</b></div><div className="policy-row"><FlaskConical size={14}/>MATLAB MCP / F3 <b>{active.backend === "matlab" ? "真实 F3" : "未调用"}</b></div>{active.error ? <p className="error-text">{active.error}</p> : null}</section></> : <div className="v2-empty inspector-empty">选择实验查看指标</div>}
      <section className="inspector-card"><h4>统一制品</h4>{artifactIndex.experiments.slice(-5).map(item => <div className="artifact-row" key={item.experimentId}><span><FileJson2 size={12}/>{item.experimentId} · {item.backend}</span><small>{item.files.length} 个文件 · {item.provenance.resultKind || "unknown"}</small></div>)}
        <div className="inspector-actions artifact-actions">
          <button className="outline-button" onClick={() => void pareto()}>查看 Pareto</button>
          <button className="outline-button" disabled={experiments.length < 2} onClick={() => void compare()}>比较实验</button>
          <button className="outline-button" disabled={!selected} onClick={() => void createResearchArtifact("/report")}>生成报告</button>
          <button className="outline-button" disabled={!selected} onClick={() => void createResearchArtifact("/export")}>复现包</button>
        </div></section>
      <section className="inspector-card"><h4>实验列表</h4>{experiments.slice(-8).map(experiment => <button className={`experiment-row ${active?.id === experiment.id ? "active" : ""}`} key={experiment.id} onClick={() => onSelectExperiment(experiment)}><span className="experiment-status"/><span>{experiment.id}<small>{solverLaneLabel(experiment.backend === "matlab" ? "matlab-mcp" : "python-fem")} · {experiment.fidelity}</small></span></button>)}</section>
    </>}
  />;
}

function Metric({ label, value }: { label: string; value: unknown }) { return <div><small>{label}</small><b>{typeof value === "number" ? value.toFixed(3) : String(value ?? "—")}</b></div>; }
