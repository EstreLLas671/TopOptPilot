import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { RotateCcw, X } from "lucide-react";
import type { EngineeringSolverLane } from "../../engineering-workspace";
import { DEFAULT_OPTIMIZATION_CONFIG, materialForPreset, validateOptimizationConfig, type MaterialConfig, type MaterialPreset, type OptimizationConfig } from "../../optimization-config";
import { solverLaneLabel } from "../../workspace";
import CaseSchematic from "./CaseSchematic";

type Props = {
  open: boolean; config: OptimizationConfig; lane: EngineeringSolverLane; busy: boolean;
  matlabDiagnostic: string; runtimeDiagnostic: string; onClose: () => void;
  onApply: (config: OptimizationConfig, lane: EngineeringSolverLane) => void;
  onRefreshEnvironment?: () => void;
};

export default function ParameterConfigurationDialog({ open, config, lane, busy, matlabDiagnostic, onClose, onApply, onRefreshEnvironment }: Props) {
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
  const updateMaterial = (value: Partial<MaterialConfig>) => setDraft(current => ({
    ...current,
    material: { ...current.material, ...value },
  }));
  const errors = validateOptimizationConfig(draft);
  return createPortal(<div className="parameter-dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="parameter-dialog" role="dialog" aria-modal="true" aria-labelledby="parameter-dialog-title" tabIndex={-1}>
      <header><div><span className="view-kicker">OPTIMIZATION CONFIGURATION</span><h2 id="parameter-dialog-title">详细参数配置</h2></div><div className="parameter-dialog-header-actions">{onRefreshEnvironment ? <button className="outline-button" aria-label="重新检测 MATLAB" disabled={busy} onClick={onRefreshEnvironment}>重新检测 MATLAB</button> : null}<button className="dialog-icon-button" aria-label="关闭详细参数" onClick={onClose}><X size={17}/></button></div></header>
      <div className="parameter-dialog-body">
        <div className="parameter-dialog-fields">
          <fieldset disabled={busy}><legend>模型与工况</legend>
            <label>求解维度<select value={draft.dimension} onChange={event => update({ dimension: event.target.value as OptimizationConfig["dimension"] })}><option value="2d">二维 2D</option><option value="3d">三维 3D</option></select></label>
            <label>工况<select value={draft.bcType} onChange={event => update({ bcType: event.target.value as OptimizationConfig["bcType"] })}><option value="cantilever">悬臂梁</option><option value="MBB">MBB 梁</option><option value="simply_supported">简支梁</option><option value="L-bracket">L 型支架</option></select></label>
            <label>精度<select value={draft.accuracy} onChange={event => update({ accuracy: event.target.value as OptimizationConfig["accuracy"] })}><option value="standard">标准</option><option value="high">高精度</option></select></label>
            <label>求解链路<select value={draftLane === "python-fem" ? "python-fem" : "local-matlab"} onChange={event => setDraftLane(event.target.value as EngineeringSolverLane)}><option value="local-matlab">本机 MATLAB（默认）</option><option value="python-fem">Python FEM</option></select></label>
          </fieldset>
          <fieldset className="material-fieldset" disabled={busy}><legend>材料</legend>
            <label className="material-preset-field">材料案例<select aria-label="材料预设" value={draft.material.preset} onChange={event => update({ material: materialForPreset(event.target.value as MaterialPreset, draft.material) })}><option value="normalized">归一化参考材料（TopOptPilot 兼容）</option><option value="structural-steel">结构钢</option><option value="aluminum-6061-t6">6061-T6 铝合金</option><option value="titanium-ti6al4v">Ti-6Al-4V 钛合金</option><option value="custom">自定义材料</option></select></label>
            <label>材料名称<input value={draft.material.name} maxLength={80} readOnly={draft.material.preset !== "custom"} onChange={event => updateMaterial({ name: event.target.value })}/></label>
            <label>杨氏模量 E（GPa）<input type="number" min="0.000001" step="0.1" value={draft.material.youngsModulusGPa} readOnly={draft.material.preset !== "custom"} onChange={event => updateMaterial({ youngsModulusGPa: Number(event.target.value) })}/></label>
            <label>泊松比 ν<input type="number" min="-0.999" max="0.499" step="0.001" value={draft.material.poissonRatio} readOnly={draft.material.preset !== "custom"} onChange={event => updateMaterial({ poissonRatio: Number(event.target.value) })}/></label>
            <label>密度（kg/m³）<input type="number" min="0.001" step="1" value={draft.material.densityKgM3} readOnly={draft.material.preset !== "custom"} onChange={event => updateMaterial({ densityKgM3: Number(event.target.value) })}/></label>
            <label>屈服强度（MPa）<input type="number" min="0.001" step="1" value={draft.material.yieldStrengthMPa} readOnly={draft.material.preset !== "custom"} onChange={event => updateMaterial({ yieldStrengthMPa: Number(event.target.value) })}/></label>
            <small className="material-model-note">E 与 ν 进入线弹性 FEM；密度和屈服强度进入运行清单与工程解释。当前目标仍是固定体积分数下最小柔度，并非重量或强度约束。</small>
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
        <aside className="parameter-dialog-preview"><h3>工况示意</h3><CaseSchematic dimension={draft.dimension} bcType={draft.bcType}/><p className="parameter-environment-diagnostic">{draftLane === "python-fem" ? "Python FEM 可用" : matlabDiagnostic}</p><div className="configuration-summary"><span>运行配置</span><code>{draft.dimension.toUpperCase()} · {draft.nelx}×{draft.nely}×{draft.dimension === "2d" ? 1 : draft.nelz}</code><code>volfrac {draft.volfrac} · penal {draft.penal} · rmin {draft.rmin}</code><code>{draft.minIterations}–{draft.maxIterations} 次 · {draft.filterStrategy}</code><span>材料摘要</span><code>{draft.material.name}</code><code>E {draft.material.youngsModulusGPa} GPa · ν {draft.material.poissonRatio}</code><code>ρ {draft.material.densityKgM3} kg/m³ · σy {draft.material.yieldStrengthMPa} MPa</code></div></aside>
      </div>
      {errors.length ? <div className="parameter-error-summary" role="alert">{errors.join("；")}</div> : null}
      <footer><button className="outline-button" disabled={busy} onClick={() => { setDraft({ ...DEFAULT_OPTIMIZATION_CONFIG }); setDraftLane("local-matlab"); }}><RotateCcw size={14}/>恢复默认</button><div className="parameter-footer-actions"><button className="outline-button" onClick={onClose}>取消</button><button className="primary-button" disabled={busy || errors.length > 0} onClick={() => onApply(draft, draftLane === "python-fem" ? "python-fem" : "local-matlab")}>应用配置</button></div></footer>
    </section>
  </div>, document.body);
}
