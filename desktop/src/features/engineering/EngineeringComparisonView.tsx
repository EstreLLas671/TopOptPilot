import { useMemo, useState } from "react";
import { CopyPlus, GitCompareArrows, Trash2 } from "lucide-react";
import type { EngineeringRun } from "../../types";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { solverLaneLabel } from "../../workspace";

export interface EngineeringParameterSet {
  lane: EngineeringSolverLane;
  nelx: number;
  nely: number;
  nelz: number;
  volfrac: number;
  maxIter: number;
}

type Snapshot = {
  id: number;
  name: string;
  config: EngineeringParameterSet;
  compliance: number | null;
  volumeFraction: number | null;
};

type Props = {
  current: EngineeringParameterSet;
  run: EngineeringRun | null;
};

function copyConfig(config: EngineeringParameterSet): EngineeringParameterSet {
  return { ...config };
}

export default function EngineeringComparisonView({ current, run }: Props) {
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const nextId = useMemo(() => Math.max(0, ...snapshots.map(item => item.id)) + 1, [snapshots]);
  const baseline = snapshots[0]?.config;
  const addSnapshot = () => setSnapshots(items => [...items, {
    id: nextId,
    name: `方案 ${nextId}`,
    config: copyConfig(current),
    compliance: run?.metrics.compliance ?? null,
    volumeFraction: run?.metrics.volumeFraction ?? null,
  }]);

  return <section className="comparison-workspace" aria-label="参数调整与对比">
    <header className="workspace-view-heading">
      <div><span className="view-kicker">CONTROLLED ENGINEERING COMPARISON</span><h2>手动参数方案对比</h2></div>
      <button className="primary-button compact" onClick={addSnapshot}><CopyPlus size={14}/>保存当前方案</button>
    </header>
    <p className="comparison-note">右侧参数修改会实时反映为“当前方案”；保存后冻结配置和当次真实运行指标。未运行的数据保持为空，不生成演示值。</p>
    <div className="comparison-table" role="table" aria-label="参数方案对比表">
      <div className="comparison-row comparison-head" role="row"><span>方案</span><span>后端</span><span>网格</span><span>体积分数</span><span>最大迭代</span><span>柔度</span><span/></div>
      <ComparisonRow name="当前方案" config={current} compliance={run?.metrics.compliance ?? null} baseline={baseline}/>
      {snapshots.map(snapshot => <ComparisonRow key={snapshot.id} name={snapshot.name} config={snapshot.config} compliance={snapshot.compliance} baseline={baseline} onRemove={() => setSnapshots(items => items.filter(item => item.id !== snapshot.id))}/>)}
    </div>
    {!snapshots.length ? <div className="view-empty comparison-empty"><GitCompareArrows size={24}/><b>尚未冻结对比方案</b><span>先在右侧调整参数，再点击“保存当前方案”。</span></div> : null}
  </section>;
}

function ComparisonRow({ name, config, compliance, baseline, onRemove }: {
  name: string;
  config: EngineeringParameterSet;
  compliance: number | null;
  baseline?: EngineeringParameterSet;
  onRemove?: () => void;
}) {
  const delta = baseline ? config.volfrac - baseline.volfrac : 0;
  return <div className="comparison-row" role="row">
    <b>{name}</b>
    <span>{solverLaneLabel(config.lane)}</span>
    <code>{config.nelx}×{config.nely}×{config.nelz}</code>
    <span>{config.volfrac.toFixed(3)} {baseline ? <small className={delta === 0 ? "" : delta > 0 ? "delta-up" : "delta-down"}>{delta === 0 ? "基准" : `${delta > 0 ? "+" : ""}${delta.toFixed(3)}`}</small> : null}</span>
    <span>{config.maxIter}</span>
    <span>{typeof compliance === "number" ? compliance.toFixed(4) : "—"}</span>
    <span>{onRemove ? <button aria-label={`删除${name}`} onClick={onRemove}><Trash2 size={13}/></button> : null}</span>
  </div>;
}