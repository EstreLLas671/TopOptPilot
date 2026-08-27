import { useEffect, useState } from "react";
import { CopyPlus, Eye, GitCompareArrows, LoaderCircle, Trash2, X } from "lucide-react";
import { api } from "../../api";
import type { EngineeringComparisonScheme, EngineeringRun } from "../../types";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { solverLaneLabel } from "../../workspace";
import EngineeringIterationView from "./EngineeringIterationView";

export interface EngineeringParameterSet {
  lane: EngineeringSolverLane; nelx: number; nely: number; nelz: number; volfrac: number; maxIter: number;
}

type Props = { current: EngineeringParameterSet; run: EngineeringRun | null; onError?: (message: string) => void };

type SchemeEvents = Array<Record<string, unknown>>;

export default function EngineeringComparisonWorkspace({ current, run, onError = () => undefined }: Props) {
  const [schemes, setSchemes] = useState<EngineeringComparisonScheme[]>([]);
  const [selected, setSelected] = useState<EngineeringComparisonScheme | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<SchemeEvents>([]);
  const [comparison, setComparison] = useState<EngineeringComparisonScheme | null>(null);
  const [comparisonEvents, setComparisonEvents] = useState<SchemeEvents>([]);
  const [busy, setBusy] = useState(false);
  const [openingId, setOpeningId] = useState("");
  const [comparisonBusy, setComparisonBusy] = useState(false);

  const load = async () => {
    try { setSchemes(await api.engineeringComparisonSchemes()); }
    catch (reason) { onError(String(reason)); }
  };
  useEffect(() => { void load(); }, []);

  async function save() {
    if (!run || run.status !== "completed") return;
    setBusy(true);
    try {
      const created = await api.engineeringComparisonSchemeCreate(run.runId);
      setSchemes(items => [created, ...items]);
    } catch (reason) { onError(String(reason)); }
    finally { setBusy(false); }
  }

  async function open(scheme: EngineeringComparisonScheme) {
    setOpeningId(scheme.id);
    try {
      const [detail, history] = await Promise.all([
        api.engineeringComparisonScheme(scheme.id),
        api.engineeringEvents(scheme.runId),
      ]);
      setSelected(detail);
      setSelectedEvents(history.events);
      setComparison(null);
      setComparisonEvents([]);
    } catch (reason) { onError(String(reason)); }
    finally { setOpeningId(""); }
  }

  async function chooseComparison(schemeId: string) {
    if (!schemeId) {
      setComparison(null);
      setComparisonEvents([]);
      return;
    }
    const scheme = schemes.find(item => item.id === schemeId);
    if (!scheme || scheme.id === selected?.id) return;
    setComparisonBusy(true);
    try {
      const [detail, history] = await Promise.all([
        api.engineeringComparisonScheme(scheme.id),
        api.engineeringEvents(scheme.runId),
      ]);
      setComparison(detail);
      setComparisonEvents(history.events);
    } catch (reason) { onError(String(reason)); }
    finally { setComparisonBusy(false); }
  }

  async function remove(scheme: EngineeringComparisonScheme) {
    if (!window.confirm("删除“" + scheme.name + "”的方案索引？真实运行和制品不会删除。")) return;
    try {
      await api.engineeringComparisonSchemeDelete(scheme.id);
      setSchemes(items => items.filter(item => item.id !== scheme.id));
      if (selected?.id === scheme.id) {
        setSelected(null);
        setSelectedEvents([]);
        setComparison(null);
        setComparisonEvents([]);
      } else if (comparison?.id === scheme.id) {
        setComparison(null);
        setComparisonEvents([]);
      }
    } catch (reason) { onError(String(reason)); }
  }

  return <section className="comparison-workspace" aria-label="参数调整与对比">
    <header className="workspace-view-heading"><div><span className="view-kicker">VERIFIED ENGINEERING COMPARISON</span><h2>参数方案与真实结果</h2></div><button className="primary-button compact" disabled={busy || !run || run.status !== "completed"} onClick={() => void save()}><CopyPlus size={14}/>{busy ? "保存中" : "保存当前运行"}</button></header>
    <p className="comparison-note">方案永久关联已完成的真实运行。打开详情后可查看真实密度与应力；选择第二个方案可并排对照，两个 3D 视图均可独立旋转和缩放。</p>
    <div className="comparison-table" role="table" aria-label="参数方案对比表">
      <div className="comparison-row comparison-head" role="row"><span>方案</span><span>后端</span><span>网格</span><span>体积分数</span><span>柔度</span><span>完整性</span><span/></div>
      <div className="comparison-row current" role="row"><b>当前配置</b><span>{solverLaneLabel(current.lane)}</span><code>{current.nelx}×{current.nely}×{current.nelz}</code><span>{current.volfrac.toFixed(3)}</span><span>{typeof run?.metrics.compliance === "number" ? run.metrics.compliance.toFixed(4) : "—"}</span><span>{run?.status || "未运行"}</span><span/></div>
      {schemes.map(scheme => <button className="comparison-row comparison-scheme-row" role="row" key={scheme.id} disabled={openingId === scheme.id} onClick={() => void open(scheme)}><b>{scheme.name}</b><span>{scheme.run ? solverLaneLabel(scheme.run.lane) : "运行缺失"}</span><code>{schemeGrid(scheme)}</code><span>{schemeVolume(scheme)}</span><span>{typeof scheme.run?.metrics.compliance === "number" ? scheme.run.metrics.compliance.toFixed(4) : "—"}</span><span className={"scheme-integrity " + scheme.integrity}>{scheme.integrity === "verified" ? "已验证" : "异常"}</span><span>{openingId === scheme.id ? <LoaderCircle className="spin" size={13}/> : <Eye size={13}/>}<i role="button" aria-label={"删除" + scheme.name} onClick={event => { event.stopPropagation(); void remove(scheme); }}><Trash2 size={13}/></i></span></button>)}
    </div>
    {!schemes.length ? <div className="view-empty comparison-empty"><GitCompareArrows size={24}/><b>尚未保存真实方案</b><span>完成一次优化后，点击“保存当前运行”。</span></div> : null}
    {selected ? <div className="scheme-detail-backdrop" role="presentation"><section className="scheme-detail-dialog" role="dialog" aria-modal="true" aria-label={selected.name}>
      <header>
        <div><span className="view-kicker">SAVED MATLAB RUN</span><h2>{selected.name}</h2><p>{selected.runId} · {new Date(selected.createdAt).toLocaleString()}</p></div>
        <div className="scheme-dialog-actions">
          <label>对照方案<select aria-label="选择对照方案" value={comparison?.id || ""} disabled={comparisonBusy} onChange={event => void chooseComparison(event.target.value)}><option value="">不对照</option>{schemes.filter(item => item.id !== selected.id).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          {comparisonBusy ? <LoaderCircle className="spin" aria-label="正在加载对照方案" size={17}/> : null}
          <button aria-label="关闭方案详情" onClick={() => { setSelected(null); setSelectedEvents([]); setComparison(null); setComparisonEvents([]); }}><X size={17}/></button>
        </div>
      </header>
      <div className="scheme-detail-content">
        <aside><h3>主方案运行配置</h3><pre>{JSON.stringify(selected.config, null, 2)}</pre><h3>配置摘要</h3><code>{selected.configDigest}</code>{comparison ? <><h3>对照方案摘要</h3><code>{comparison.configDigest}</code></> : null}<p>3D 方案显示真实 MATLAB 密度/应力等值曲面，可切换单元网格；2D 方案保持真实二维场。</p></aside>
        <div className={"scheme-visual-comparison " + (comparison ? "dual" : "single")}>
          <SchemeResult label="主方案" scheme={selected} events={selectedEvents} />
          {comparison ? <SchemeResult label="对照方案" scheme={comparison} events={comparisonEvents} /> : null}
        </div>
      </div>
    </section></div> : null}
  </section>;
}

function SchemeResult({ label, scheme, events }: { label: string; scheme: EngineeringComparisonScheme; events: SchemeEvents }) {
  return <article className="scheme-result-column" aria-label={label + " " + scheme.name}>
    <header><span>{label}</span><div><b>{scheme.name}</b><small>{schemeGrid(scheme)} · {scheme.run ? solverLaneLabel(scheme.run.lane) : "运行缺失"}</small></div></header>
    {scheme.integrity !== "verified" ? <div className="scheme-integrity-warning">制品完整性异常：{scheme.integrityFailures.join("、") || "缺少已验证制品"}</div> : null}
    <EngineeringIterationView run={scheme.run} events={events} maxIterations={Number(scheme.config.maxIterations || 60)} compact />
  </article>;
}

function schemeGrid(scheme: EngineeringComparisonScheme): string {
  const task = scheme.config.task as Record<string, unknown> | undefined;
  const geometry = (task?.geometry as Record<string, unknown> | undefined) || (scheme.config.geometry as Record<string, unknown> | undefined) || {};
  return [geometry.nelx, geometry.nely, geometry.nelz].filter(value => value !== undefined).join("×") || "—";
}
function schemeVolume(scheme: EngineeringComparisonScheme): string {
  const task = scheme.config.task as Record<string, unknown> | undefined;
  const params = (task?.params as Record<string, unknown> | undefined) || (scheme.config.params as Record<string, unknown> | undefined) || {};
  return typeof params.volfrac === "number" ? params.volfrac.toFixed(3) : "—";
}
