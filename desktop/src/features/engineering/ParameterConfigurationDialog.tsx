import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { RotateCcw, X } from "lucide-react";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { DEFAULT_OPTIMIZATION_CONFIG, validateOptimizationConfig, type OptimizationConfig } from "../../optimization-config";
import { solverLaneLabel } from "../../workspace";
import CaseSchematic from "./CaseSchematic";

type Props = {
  open: boolean; config: OptimizationConfig; lane: EngineeringSolverLane; busy: boolean;
  matlabDiagnostic: string; runtimeDiagnostic: string; onClose: () => void;
  onApply: (config: OptimizationConfig, lane: EngineeringSolverLane) => void;
};

export default function ParameterConfigurationDialog({ open, config, lane, busy, matlabDiagnostic, runtimeDiagnostic, onClose, onApply }: Props) {
  const [draft, setDraft] = useState(config);
  const [draftLane, setDraftLane] = useState(lane);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => { if (open) { setDraft({ ...config }); setDraftLane(lane); } }, [open, config, lane]);
  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusableSelector = "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex='-1'])";
    const focusFirst = () => dialogRef.current?.querySelector<HTMLElement>(focusableSelector)?.focus();
    const frame = window.requestAnimationFrame(focusFirst);
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !dialogRef.current) return;
      const focusable = Array.from(dialogRef.current.querySelectorAll<HTMLElement>(focusableSelector));
      if (!focusable.length) {
        event.preventDefault();
        dialogRef.current.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  const update = (value: Partial<OptimizationConfig>) => setDraft(current => ({ ...current, ...value }));
  const errors = validateOptimizationConfig(draft);
  return createPortal(<div className="parameter-dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="parameter-dialog" role="dialog" aria-modal="true" aria-labelledby="parameter-dialog-title" tabIndex={-1}>
      <header><div><span className="view-kicker">OPTIMIZATION CONFIGURATION</span><h2 id="parameter-dialog-title">详细参数配置</h2><p>修改暂存在此窗口，点击“应用配置”后才会更新工程工作区。</p></div><button className="dialog-icon-button" aria-label="关闭详细参数" onClick={onClose}><X size={17}/></button></header>
      <div className="parameter-dialog-body">
        <div className="parameter-dialog-fields">
          <fieldset disabled={busy}><legend>模型与工况</legend>
            <label>求解维度<select value={draft.dimension} onChange={event => update({ dimension: event.target.value as OptimizationConfig["dimension"] })}><option value="2d">二维 2D</option><option value="3d">三维 3D</option></select></label>
            <label>工况<select value={draft.bcType} onChange={event => update({ bcType: event.target.value as OptimizationConfig["bcType"] })}><option value="cantilever">悬臂梁</option><option value="MBB">MBB 梁</option><option value="simply_supported">简支梁</option><option value="L-bracket">L 型支架</option></select></label>
            <label>精度<select value={draft.accuracy} onChange={event => update({ accuracy: event.target.value as OptimizationConfig["accuracy"] })}><option value="standard">标准</option><option value="high">高精度</option></select></label>
            <label>求解链路<select value={draftLane} onChange={event => setDraftLane(event.target.value as EngineeringSolverLane)}><option value="local-matlab">本机 MATLAB（默认）</option><option value="python-fem">Python FEM</option><option value="compiled-runtime">编译 Runtime（可选）</option></select></label>
          </fieldset>
          <fieldset disabled={busy}><legend>网格与优化</legend>
            <label>X 单元<input type="number" min="1" value={draft.nelx} onChange={event => update({ nelx: Number(event.target.value) })}/></label><label>Y 单元<input type="number" min="1" value={draft.nely} onChange={event => update({ nely: Number(event.target.value) })}/></label>
            {draft.dimension === "3d" ? <label>Z 单元<input type="number" min="1" value={draft.nelz} onChange={event => update({ nelz: Number(event.target.value) })}/></label> : <label>Z 单元<input value="2D 固定为 1" disabled/></label>}
            <label>体积分数<input type="number" min="0.01" max="1" step="0.01" value={draft.volfrac} onChange={event => update({ volfrac: Number(event.target.value) })}/></label>
            <label>惩罚因子 penal<input type="number" min="1" max="5" step="0.1" value={draft.penal} onChange={event => update({ penal: Number(event.target.value) })}/></label><label>滤波半径 rmin<input type="number" min="0.1" step="0.1" value={draft.rmin} onChange={event => update({ rmin: Number(event.target.value) })}/></label>
            <label>最小迭代<input type="number" min="1" value={draft.minIterations} onChange={event => update({ minIterations: Number(event.target.value) })}/></label><label>最大迭代<input type="number" min="1" max="2000" value={draft.maxIterations} onChange={event => update({ maxIterations: Number(event.target.value) })}/></label>
            <label>滤波策略<select value={draft.filterStrategy} onChange={event => update({ filterStrategy: event.target.value as OptimizationConfig["filterStrategy"] })}><option value="fixed">固定半径</option><option value="adaptive">自适应半径</option></select></label>
          </fieldset>
        </div>
        <aside className="parameter-dialog-preview"><h3>工况示意</h3><CaseSchematic dimension={draft.dimension} bcType={draft.bcType}/><div className="configuration-readiness"><div><span>当前链路</span><b>{solverLaneLabel(draftLane)}</b></div><p>{draftLane === "local-matlab" ? matlabDiagnostic : draftLane === "compiled-runtime" ? runtimeDiagnostic : "安装包内置 Python FEM sidecar"}</p></div><div className="configuration-summary"><span>运行配置</span><code>{draft.dimension.toUpperCase()} · {draft.nelx}×{draft.nely}×{draft.dimension === "2d" ? 1 : draft.nelz}</code><code>volfrac {draft.volfrac} · penal {draft.penal} · rmin {draft.rmin}</code><code>{draft.minIterations}–{draft.maxIterations} 次 · {draft.filterStrategy}</code></div></aside>
      </div>
      <footer><button className="outline-button" disabled={busy} onClick={() => setDraft({ ...DEFAULT_OPTIMIZATION_CONFIG })}><RotateCcw size={14}/>恢复默认</button><span>{errors.length ? <em>{errors.join("；")}</em> : "配置校验通过"}</span><button className="outline-button" onClick={onClose}>取消</button><button className="primary-button" disabled={busy || errors.length > 0} onClick={() => onApply(draft, draftLane)}>应用配置</button></footer>
    </section>
  </div>, document.body);
}
