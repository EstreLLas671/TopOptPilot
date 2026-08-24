import { useEffect, useMemo, useState } from "react";
import { Activity, CheckCircle2, Radio } from "lucide-react";
import type { EngineeringRun } from "../../types";

type ProgressFrame = {
  iteration: number;
  compliance: number | null;
  volumeFraction: number | null;
  grayRatio: number | null;
};

type Props = {
  run: EngineeringRun | null;
  events: Array<Record<string, unknown>>;
};

function finiteOrNull(value: unknown): number | null {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export default function EngineeringIterationView({ run, events }: Props) {
  const frames = useMemo<ProgressFrame[]>(() => events.flatMap(event => {
    if (event.type !== "progress") return [];
    const metrics = event.metrics && typeof event.metrics === "object"
      ? event.metrics as Record<string, unknown>
      : {};
    const iteration = Number(event.iteration ?? metrics.iteration);
    if (!Number.isFinite(iteration)) return [];
    return [{
      iteration,
      compliance: finiteOrNull(metrics.compliance),
      volumeFraction: finiteOrNull(metrics.volumeFraction),
      grayRatio: finiteOrNull(metrics.grayRatio),
    }];
  }), [events]);
  const [followLatest, setFollowLatest] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    if (followLatest && frames.length) setSelectedIndex(frames.length - 1);
  }, [followLatest, frames.length]);

  const selected = frames[Math.min(selectedIndex, Math.max(frames.length - 1, 0))];
  return <section className="iteration-workspace" aria-label="迭代可视化">
    <header className="workspace-view-heading">
      <div><span className="view-kicker">REAL-TIME SOLVER EVIDENCE</span><h2>迭代时间轴</h2></div>
      <label className="follow-latest"><input type="checkbox" checked={followLatest} onChange={event => setFollowLatest(event.target.checked)}/><Radio size={13}/>跟随最新</label>
    </header>
    <div className="iteration-stage">
      <section className="iteration-canvas">
        <div className="canvas-label"><Activity size={14}/>密度 / 应力快照</div>
        {selected ? <div className="iteration-placeholder">
          <div className="iteration-pulse"><span/><span/><span/><span/><span/></div>
          <b>第 {selected.iteration} 轮</b>
          <small>当前显示的是后端事件中的真实迭代指标；二进制密度和应力帧只在制品摘要校验后读取。</small>
        </div> : <div className="view-empty"><Activity size={24}/><b>等待真实迭代快照</b><span>启动求解后，时间轴会跟随 WebSocket progress 事件。</span></div>}
      </section>
      <aside className="iteration-metrics">
        <Metric label="状态" value={run?.status ?? "idle"}/>
        <Metric label="迭代" value={selected?.iteration ?? run?.metrics.iteration ?? "—"}/>
        <Metric label="柔度" value={selected?.compliance}/>
        <Metric label="体积分数" value={selected?.volumeFraction}/>
        <Metric label="灰度率" value={selected?.grayRatio}/>
      </aside>
    </div>
    <div className="iteration-scrubber">
      <input
        aria-label="选择迭代轮次"
        type="range"
        min={0}
        max={Math.max(0, frames.length - 1)}
        value={Math.min(selectedIndex, Math.max(frames.length - 1, 0))}
        disabled={!frames.length}
        onChange={event => { setFollowLatest(false); setSelectedIndex(Number(event.target.value)); }}
      />
      <span>{frames.length ? `${selectedIndex + 1} / ${frames.length}` : "0 / 0"}</span>
    </div>
    <div className="snapshot-ledger">
      {run?.snapshots.slice(-8).map(snapshot => <div key={snapshot.sha256}><CheckCircle2 size={12}/><span>{snapshot.relativePath}</span><code>{snapshot.sha256.slice(0, 12)}</code></div>)}
      {!run?.snapshots.length ? <small>尚无已索引快照制品。</small> : null}
    </div>
  </section>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  const display = typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : String(value ?? "—");
  return <div><small>{label}</small><b>{display}</b></div>;
}