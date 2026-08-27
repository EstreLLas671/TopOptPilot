import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Activity, BookOpen, Bot, Boxes, Check, ChevronRight, CircleAlert, FlaskConical,
  Languages, LoaderCircle, MessageSquare, Play, Plus, RefreshCw, Send, Settings2,
  ShieldCheck, SquareTerminal, X } from "lucide-react";
import i18n from "./i18n";
import { api, initializeBackend } from "./api";
import type { AppSettings, Decision, EventRecord, Experiment, Locale, MatlabHealth, Research } from "./types";
import SettingsWorkspace from "./SettingsWorkspace";
import ResearchSetup from "./ResearchSetup";
import ExperimentCanvas, { type CanvasView } from "./ExperimentCanvas";
import HealthBar from "./HealthBar";
import KnowledgeCenter from "./KnowledgeCenter";
import type { SystemHealth } from "./types";
import "./v6.css";

const statusClass = (status: string) => `status status-${status.toLowerCase().replaceAll("_", "-")}`;
const fmt = (value: unknown, digits = 4) => typeof value === "number" && Number.isFinite(value)
  ? value.toFixed(digits) : "—";

function TopologyCanvas({ density }: { density?: unknown[] }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (!canvas.current || !Array.isArray(density) || !density.length) return;
    let grid: number[][] = density as number[][];
    if (Array.isArray(grid[0]?.[0])) {
      const volume = density as unknown as number[][][];
      grid = volume.map(row => row.map(column => Math.max(...column)));
    }
    const height = grid.length, width = grid[0]?.length || 0;
    if (!width) return;
    const context = canvas.current.getContext("2d")!;
    canvas.current.width = Math.max(320, width * 5);
    canvas.current.height = Math.max(130, height * 5);
    context.fillStyle = "#f6f7f8"; context.fillRect(0, 0, canvas.current.width, canvas.current.height);
    const cw = canvas.current.width / width, ch = canvas.current.height / height;
    grid.forEach((row, y) => row.forEach((raw, x) => {
      const value = Math.max(0, Math.min(1, Number(raw)));
      const shade = Math.round(247 - value * 220);
      context.fillStyle = `rgb(${shade},${shade + Math.round(value * 8)},${shade + Math.round(value * 14)})`;
      context.fillRect(x * cw, y * ch, Math.ceil(cw), Math.ceil(ch));
    }));
  }, [density]);
  return <canvas className="topology-canvas" ref={canvas} />;
}

function Convergence({ history }: { history?: Array<Record<string, number>> }) {
  if (!history?.length) return <div className="empty-mini">—</div>;
  const values = history.map(item => Number(item.compliance)).filter(Number.isFinite);
  if (!values.length) return null;
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(1e-9, max - min);
  const points = values.map((value, index) => `${(index / Math.max(1, values.length - 1)) * 300},${92 - ((value - min) / span) * 78}`).join(" ");
  return <svg className="convergence" viewBox="0 0 300 100" preserveAspectRatio="none"><polyline points={points} /></svg>;
}

function App() {
  const { t } = useTranslation();
  const [ready, setReady] = useState(false), [error, setError] = useState("");
  const [researches, setResearches] = useState<Research[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [research, setResearch] = useState<Research | null>(null);
  const [selectedExp, setSelectedExp] = useState<string | null>(null);
  const [matlab, setMatlab] = useState<MatlabHealth | null>(null);
  const [command, setCommand] = useState(""), [busy, setBusy] = useState(false);
  const [createOpen, setCreateOpen] = useState(false), [editDecision, setEditDecision] = useState<Decision | null>(null);
  const [streamText, setStreamText] = useState("");
  const [settings, setSettings] = useState<AppSettings | null>(null), [settingsOpen, setSettingsOpen] = useState(false);
  const [health,setHealth]=useState<SystemHealth|null>(null),[canvasView,setCanvasView]=useState<CanvasView>("PLAN");
  const [knowledgeOpen,setKnowledgeOpen]=useState(false);

  const refreshList = useCallback(async () => {
    const values = await api.listResearch(); setResearches(values);
    if (!selectedId && values.length) setSelectedId(values[0].id);
  }, [selectedId]);
  const refreshResearch = useCallback(async () => {
    if (selectedId) setResearch(await api.getResearch(selectedId));
  }, [selectedId]);

  useEffect(() => { (async () => {
    try { await initializeBackend(); const appSettings=await api.settings(); setSettings(appSettings);
      await i18n.changeLanguage(appSettings.locale); document.documentElement.lang=appSettings.locale;
      document.documentElement.dataset.density=appSettings.ui_density; await refreshList();
      const [matlabHealth,systemHealth]=await Promise.all([api.matlabHealth(),api.health()]);setMatlab(matlabHealth);setHealth(systemHealth);setReady(true); }
    catch (reason) { setError(String(reason)); }
  })(); }, []);
  useEffect(() => { refreshResearch().catch(reason => setError(String(reason))); }, [refreshResearch]);
  useEffect(() => {
    if (!ready || !selectedId) return;
    let ws:WebSocket|undefined,disposed=false;
    api.stream(selectedId).then(socket=>{if(disposed){socket.close();return}ws=socket;ws.onmessage = event => {
      const message = JSON.parse(event.data);
      if (message.type === "events" || message.type === "progress") refreshResearch();
      if (message.type === "agent_session") setStreamText(message.session?.stream_text || "");
    };ws.onclose=()=>{if(!disposed)setTimeout(()=>refreshResearch(),500)}}).catch(reason=>setError(String(reason)));
    return () => {disposed=true;ws?.close()};
  }, [ready, selectedId, refreshResearch]);

  useEffect(()=>{if(!research)return;const pending=research.decisions.some(item=>item.status==="PENDING"),running=research.experiments.some(item=>item.status==="RUNNING");setCanvasView(current=>{if(["SETUP","HYPOTHESIS","COMPARE","REPORT","TIMELINE"].includes(current))return current;if(running)return "RUN";if(pending)return "DECIDE";if(research.experiments.some(item=>item.result))return "ANALYZE";return "PLAN"})},[research?.id,research?.status,research?.experiments.length,research?.decisions.length]);

  const selected = useMemo(() => research?.experiments.find(item => item.id === selectedExp)
    || research?.experiments.find(item => item.status === "RUNNING") || research?.best_experiment
    || research?.experiments.at(-1), [research, selectedExp]);
  const rounds = useMemo(() => (research?.experiments || []).reduce<Record<string,Experiment[]>>((value,exp)=>{
    const key=`Round ${exp.round_number||1}`;(value[key] ||= []).push(exp);return value;
  },{}),[research?.experiments]);

  async function runCommand(text = command) {
    if (!research || !text.trim()) return;
    setBusy(true);
    try { await api.command(research.id, text.trim(), selected?.id); setCommand(""); await refreshResearch(); }
    catch (reason) { setError(String(reason)); } finally { setBusy(false); }
  }
  async function changeLanguage() {
    const locale: Locale = i18n.language === "zh-CN" ? "en-US" : "zh-CN";
    await i18n.changeLanguage(locale); localStorage.setItem("topoptpilot.locale", locale);
    document.documentElement.lang = locale;
    if (research) { await api.setLocale(research.id, locale); await refreshResearch(); }
    if (settings) setSettings(await api.saveSettings({locale}));
  }
  async function resolveDecision(decision: Decision, action: "approve" | "reject" | "why") {
    try {
      if (action === "approve") await api.approve(decision.id);
      if (action === "reject") await api.reject(decision.id);
      if (action === "why") alert((await api.why(decision.id)).reason);
      await refreshResearch();
    } catch (reason) { setError(String(reason)); }
  }

  if (!ready) return <div className="boot"><LoaderCircle className="spin"/><h2>{t("loading")}</h2>{error && <><p>{t("serviceError")}: {error}</p><button onClick={() => window.location.reload()}><RefreshCw size={15}/>{t("retry")}</button></>}</div>;
  if (settingsOpen && settings) return <SettingsWorkspace settings={settings} onClose={() => setSettingsOpen(false)} onSaved={async value => { setSettings(value); await i18n.changeLanguage(value.locale); document.documentElement.lang=value.locale; document.documentElement.dataset.density=value.ui_density; if(research) await api.setLocale(research.id,value.locale); }}/>
  if (knowledgeOpen) return <KnowledgeCenter locale={i18n.language as Locale} onClose={()=>setKnowledgeOpen(false)}/>
  return <div className="app-shell">
    <header className="titlebar" data-tauri-drag-region>
      <div className="brand"><div className="brand-mark"><Boxes size={18}/></div><span>{t("appName")}</span><small>RESEARCH WORKSPACE</small></div>
      <div className="title-center">{research?.id || "LOCAL"} {research && <span className={statusClass(research.status)}>{research.status}</span>}<HealthBar health={health} onRefresh={()=>api.health().then(setHealth).catch(reason=>setError(String(reason)))}/></div>
      <div className="title-actions">
        <button className="ghost" onClick={()=>setKnowledgeOpen(true)}><BookOpen size={16}/>{i18n.language === "zh-CN" ? "知识" : "Knowledge"}</button>
        <button className="ghost" onClick={changeLanguage}><Languages size={16}/>{t("language")}</button>
        <button className="ghost" onClick={() => setSettingsOpen(true)}><Settings2 size={16}/>{i18n.language === "zh-CN" ? "设置" : "Settings"}</button>
      </div>
    </header>
    {error && <div className="error-banner"><CircleAlert size={16}/><span>{error}</span><button onClick={() => setError("")}><X size={15}/></button></div>}
    <main className="workspace">
      <aside className="explorer">
        <div className="pane-heading"><span>{t("research")}</span><button title={t("newResearch")} onClick={() => setCreateOpen(true)}><Plus size={16}/></button></div>
        <div className="research-list">{researches.map(item => <button key={item.id} className={`research-item ${item.id === selectedId ? "selected" : ""}`} onClick={() => {setSelectedId(item.id);setSelectedExp(null)}}>
          <FlaskConical size={16}/><span><b>{item.name}</b><small>{item.id} · {item.status}</small></span><ChevronRight size={14}/></button>)}</div>
        {research && <>
          <section className="tree-section"><h4>{t("goal")}</h4><p>{research.goal}</p></section>
          <section className="tree-section grow"><h4>{t("experiments")} <em>{research.experiments.length}</em></h4>
            <div className="experiment-list">{Object.entries(rounds).map(([round,items])=><div className="round-group" key={round}><h5>{round}</h5>{items.map(exp => <button key={exp.id} className={exp.id === selected?.id ? "active" : ""} onClick={() => {setSelectedExp(exp.id);setCanvasView(exp.status==="RUNNING"?"RUN":"ANALYZE")}}>
              <span className={`run-icon run-${exp.status.toLowerCase()}`}>{exp.status === "SUCCESS" ? <Check/> : exp.status === "RUNNING" ? <LoaderCircle className="spin"/> : <Activity/>}</span>
              <span><b>{exp.id}</b><small>{exp.fidelity} · {exp.decision_source||"HUMAN"}</small></span><em>{Math.round((exp.progress || 0) * 100)}%</em></button>)}</div>)}</div>
          </section>
          <div className="budget"><span>{t("budget")}</span><b>{research.budget_used}/{research.budget_total}</b><div><i style={{width:`${Math.min(100,research.budget_used/research.budget_total*100)}%`}}/></div></div>
        </>}
      </aside>

      <section className="stream-pane">
        {research?<ExperimentCanvas research={research} selected={selected} streamText={streamText} view={canvasView} setView={setCanvasView} onSelect={setSelectedExp} onAutonomous={()=>api.autonomous(research.id).then(refreshResearch)} onDecision={resolveDecision} onEdit={setEditDecision}/>:<div className="empty-state"><FlaskConical size={38}/><h2>{t("noResearch")}</h2></div>}
        <div className="composer"><SquareTerminal size={18}/><textarea value={command} disabled={!research || busy} placeholder={t("commandPlaceholder")} onChange={e => setCommand(e.target.value)} onKeyDown={e => {if(e.key === "Enter" && !e.shiftKey){e.preventDefault();runCommand()}}}/><button disabled={!command.trim() || busy} onClick={() => runCommand()}>{busy ? <LoaderCircle className="spin"/> : <Send/>}</button></div>
      </section>

      <aside className="inspector">
        <div className="pane-heading"><span>{t("inspector")}</span><button onClick={() => {refreshResearch();api.matlabHealth().then(setMatlab)}}><RefreshCw size={15}/></button></div>
        <section className="health-card"><header><span><Settings2 size={15}/>{t("matlab")}</span><span className={statusClass(matlab?.state || "UNAVAILABLE")}>{matlab?.state || "—"}</span></header><p>{matlab?.matlab_root || t("unavailable")}</p><small>{t("matlabStrict")}</small><button onClick={() => api.restartMatlab().then(setMatlab)}><RefreshCw size={14}/>{t("restart")}</button></section>
        {selected ? <>
          <section className="inspect-section"><div className="run-title"><span><b>{selected.id}</b><small>{selected.fidelity}</small></span><span className={statusClass(selected.status)}>{selected.status}</span></div><div className="provenance-table"><div><span>Result source</span><b>{selected.result_source||"LIVE_REAL_RUN"}</b></div><div><span>Decision source</span><b>{selected.decision_source||"HUMAN"}</b></div><div><span>Policy</span><b>{selected.policy_version||"—"}</b></div><div><span>Model</span><b>{selected.model||"—"}</b></div></div>{selected.error && <p className="run-error">{selected.error}</p>}</section>
          <section className="inspect-section"><h4>{t("metrics")}</h4><div className="metric-grid"><Metric label={t("compliance")} value={fmt(selected.result?.objective?.compliance,2)}/><Metric label={t("gray")} value={fmt(selected.result?.quality?.gray_ratio)}/><Metric label={t("components")} value={selected.result?.quality?.connected_components ?? "—"}/><Metric label={t("backend")} value={String(selected.result?.solver?.backend || selected.backend)}/></div></section>
          {selected.result?.evaluation&&<section className="inspect-section"><h4>Evaluator</h4><div className="provenance-table">{Object.entries(selected.result.evaluation).filter(([,value])=>typeof value!=="object").map(([key,value])=><div key={key}><span>{key}</span><b>{String(value)}</b></div>)}</div></section>}
          {selected.backend==="matlab"&&<section className="inspect-section"><h4>REAL MATLAB EVIDENCE</h4><div className="provenance-table">{Object.entries(selected.result?.solver||{}).filter(([key])=>["backend","matlab_version","mcp_version","mcp_binary_sha256","solver_entry","solver_entry_sha256","task_sha256"].includes(key)).map(([key,value])=><div key={key}><span>{key}</span><b>{String(value)}</b></div>)}</div></section>}
          <section className="inspect-section"><h4>{t("topology")}</h4><TopologyCanvas density={selected.result?.artifacts?.density}/></section>
          <section className="inspect-section"><h4>{t("convergence")}</h4><Convergence history={selected.result?.artifacts?.history}/></section>
          <section className="inspect-section"><h4>{t("parameters")}</h4><div className="param-table">{Object.entries(selected.parameters).map(([key,value]) => <div key={key}><span>{key}</span><code>{String(value)}</code></div>)}</div></section>
          <section className="inspect-section"><h4>Solver Variant</h4><div className="provenance-table"><div><span>Variant</span><b>{selected.solver_variant||String(selected.result?.solver?.solver_variant||"reference_cpu")}</b></div><div><span>Acceleration</span><b>{selected.acceleration_mode||String(selected.result?.solver?.acceleration_mode||"cpu")}</b></div><div><span>Task hash</span><b>{selected.task_hash||String(selected.result?.solver?.task_sha256||"—")}</b></div><div><span>Review</span><b>{selected.review_verdict||"—"}</b></div><div><span>Human</span><b>{selected.human_decision||"—"}</b></div></div></section>
          {!!research?.subagent_tasks?.length&&<section className="inspect-section"><h4>Subagent Review</h4><div className="provenance-table">{research.subagent_tasks.slice(-5).map(task=><div key={task.id}><span>{task.role}</span><b>{task.status}</b></div>)}</div></section>}
        </> : research?<><section className="inspect-section"><h4>RESEARCH CONTRACT</h4><div className="provenance-table"><div><span>{t("goal")}</span><b>{research.goal}</b></div><div><span>{t("status")}</span><b>{research.status}</b></div><div><span>Mode</span><b>{research.mode}</b></div><div><span>{t("budget")}</span><b>{research.budget_used}/{research.budget_total}</b></div><div><span>Contract</span><b>{research.contract?.immutable?"IMMUTABLE":"LEGACY"}</b></div></div></section><section className="inspect-section"><h4>{t("constraints")}</h4><div className="param-table">{Object.entries(research.constraints).map(([key,value])=><div key={key}><span>{key}</span><code>{String(value)}</code></div>)}</div></section></>:<div className="empty-state compact">{t("currentRun")}: —</div>}
        {research && <div className="inspector-actions"><button onClick={() => runCommand("/report")}>{t("report")}</button><button onClick={() => runCommand("/export")}>{t("export")}</button></div>}
      </aside>
    </main>
    {createOpen && <ResearchSetup locale={i18n.language as Locale} onClose={() => setCreateOpen(false)} onCreate={async data => {const value=await api.createResearch(data);setCreateOpen(false);await refreshList();setSelectedId(value.id)}}/>}
    {editDecision && <EditDecision t={t} decision={editDecision} onClose={() => setEditDecision(null)} onSave={async params => {await api.editDecision(editDecision.id,params);setEditDecision(null);await refreshResearch()}}/>}
  </div>;
}

function EventCard({ event }: { event: EventRecord }) {
  const agent = event.kind.includes("AGENT"), tool = event.kind.includes("TOOL"), evidence = event.kind === "EVIDENCE";
  return <article className={`event-card ${agent ? "agent" : tool ? "tool" : evidence ? "evidence" : ""}`}><div className="event-icon">{agent ? <Bot/> : tool ? <SquareTerminal/> : evidence ? <ShieldCheck/> : <Activity/>}</div><div><header><span>{event.kind}</span><time>{new Date(event.created_at).toLocaleTimeString()}</time></header><h3>{event.title}</h3><p>{event.body}</p></div></article>;
}
function DecisionCard({decision,t,onAction,onEdit}:{decision:Decision;t:(key:string)=>string;onAction:(d:Decision,a:"approve"|"reject"|"why")=>void;onEdit:(d:Decision)=>void}) {
  return <article className="decision-card"><header><ShieldCheck/> AI PROPOSAL <span>{decision.risk}</span></header><h3>{decision.proposal.fidelity}</h3><p>{decision.reason}</p><pre>{JSON.stringify(decision.proposal.parameters,null,2)}</pre><div><button className="approve" onClick={()=>onAction(decision,"approve")}>{t("approve")}</button><button onClick={()=>onEdit(decision)}>{t("edit")}</button><button onClick={()=>onAction(decision,"reject")}>{t("reject")}</button><button onClick={()=>onAction(decision,"why")}>{t("why")}</button></div></article>;
}
function Metric({label,value}:{label:string;value:unknown}) { return <div><span>{label}</span><b>{String(value)}</b></div>; }
function CreateResearch({t,locale,onClose,onCreate}:{t:(k:string)=>string;locale:Locale;onClose:()=>void;onCreate:(v:object)=>Promise<void>}) {
  const [name,setName]=useState(locale==="zh-CN"?"新拓扑优化研究":"New topology study"), [goal,setGoal]=useState(locale==="zh-CN"?"在满足体积分数和连通性约束下最小化柔度。":"Minimize compliance subject to volume and connectivity constraints.");
  return <div className="modal-backdrop"><form className="modal" onSubmit={e=>{e.preventDefault();onCreate({name,goal,locale})}}><header><h2>{t("newResearch")}</h2><button type="button" onClick={onClose}><X/></button></header><p>{t("createHint")}</p><label>{t("name")}<input value={name} onChange={e=>setName(e.target.value)}/></label><label>{t("goal")}<textarea value={goal} onChange={e=>setGoal(e.target.value)}/></label><p>预算、模式和求解器模板使用设置中心中的“新研究默认值”。</p><footer><button type="button" onClick={onClose}>{t("cancel")}</button><button className="approve" type="submit">{t("create")}</button></footer></form></div>;
}
function EditDecision({t,decision,onClose,onSave}:{t:(k:string)=>string;decision:Decision;onClose:()=>void;onSave:(p:Record<string,unknown>)=>Promise<void>}) {
  const [text,setText]=useState(JSON.stringify(decision.proposal.parameters||{},null,2)), [error,setError]=useState("");
  return <div className="modal-backdrop"><form className="modal" onSubmit={e=>{e.preventDefault();try{onSave(JSON.parse(text))}catch(reason){setError(String(reason))}}}><header><h2>{t("edit")} {decision.id}</h2><button type="button" onClick={onClose}><X/></button></header><textarea className="json-editor" value={text} onChange={e=>setText(e.target.value)}/>{error&&<p className="run-error">{error}</p>}<footer><button type="button" onClick={onClose}>{t("cancel")}</button><button className="approve" type="submit">{t("save")}</button></footer></form></div>;
}
export default App;
