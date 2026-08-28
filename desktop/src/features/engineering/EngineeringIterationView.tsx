import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, CheckCircle2, Radio, RefreshCw } from "lucide-react";
import { engineeringArtifactBuffer } from "../../backend-artifact";
import type { EngineeringRun } from "../../types";
import { asFortranVolume, projectFortranVolume, readFloat32LittleEndian, type MatlabVolume } from "./matlab-artifact";
import InteractiveVolumeView, { type ViewState } from "./InteractiveVolumeView";
import { ScalarMap } from "./ResultViewer";

type SnapshotDescriptor = {
  densityPath: string;
  stressPath: string | null;
  renderPath: string | null;
  shape: number[];
  dimension: "2d" | "3d";
  densitySha256?: string;
  stressSha256?: string;
  renderSha256?: string;
};

type ProgressFrame = {
  iteration: number;
  compliance: number | null;
  volumeFraction: number | null;
  grayRatio: number | null;
  snapshot: SnapshotDescriptor | null;
};

type Props = {
  run: EngineeringRun | null;
  events: Array<Record<string, unknown>>;
  maxIterations: number;
  compact?: boolean;
};
type CachedSnapshot = {
  density: number[][];
  stress: number[][];
  densityVolume: MatlabVolume;
  stressVolume: MatlabVolume | null;
  renderUrl: string;
};

function finiteOrNull(value: unknown): number | null {
  if (value === null || value === undefined || typeof value === "boolean") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function snapshotFrom(value: unknown): SnapshotDescriptor | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const shape = Array.isArray(raw.shape) ? raw.shape.map(Number) : [];
  if (![2, 3].includes(shape.length) || shape.some(item => !Number.isInteger(item) || item < 1)) return null;
  if (typeof raw.densityPath !== "string" || !raw.densityPath.startsWith("snapshots/")) return null;
  return {
    densityPath: raw.densityPath,
    stressPath: typeof raw.stressPath === "string" && raw.stressPath.startsWith("snapshots/") ? raw.stressPath : null,
    renderPath: typeof raw.renderPath === "string" && raw.renderPath.startsWith("snapshots/") ? raw.renderPath : null,
    shape,
    dimension: raw.dimension === "2d" ? "2d" : "3d",
    densitySha256: typeof raw.densitySha256 === "string" ? raw.densitySha256 : undefined,
    stressSha256: typeof raw.stressSha256 === "string" ? raw.stressSha256 : undefined,
    renderSha256: typeof raw.renderSha256 === "string" ? raw.renderSha256 : undefined,
  };
}

export default function EngineeringIterationView({ run, events, maxIterations, compact = false }: Props) {
  const [volumeViewState, setVolumeViewState] = useState<ViewState>({ rotationX: -0.52, rotationY: 0.72, zoom: 1 });
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
      snapshot: snapshotFrom(event.snapshot),
    }];
  }), [events]);
  const latestConsole = useMemo(() => {
    const event = [...events].reverse().find(item => item.type === "console" && typeof item.text === "string");
    return event ? String(event.text).trim() : "";
  }, [events]);
  const [followLatest, setFollowLatest] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [fieldMode, setFieldMode] = useState<"matlab" | "density" | "stress">("matlab");
  const [density, setDensity] = useState<number[][]>([]);
  const [stress, setStress] = useState<number[][]>([]);
  const [densityVolume, setDensityVolume] = useState<MatlabVolume | null>(null);
  const [stressVolume, setStressVolume] = useState<MatlabVolume | null>(null);
  const [renderUrl, setRenderUrl] = useState("");
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");
  const snapshotCache = useRef(new Map<string, CachedSnapshot>());
  const snapshotRequests = useRef(new Map<string, Promise<CachedSnapshot>>());
  useEffect(() => {
    // A new run always starts on the real MATLAB image and follows its latest frame.
    setFieldMode("matlab");
    setFollowLatest(true);
    setSelectedIndex(0);
    setDensity([]);
    setStress([]);
    setDensityVolume(null);
    setStressVolume(null);
    setRenderUrl("");
    setSnapshotError("");
  }, [run?.runId]);
  useEffect(() => () => {
    // Release image URLs when the run changes or the view unmounts. The cache
    // remains available for the lifetime of one run, so dragging its slider
    // never has to re-read an already loaded frame.
    for (const cached of snapshotCache.current.values()) if (cached.renderUrl) URL.revokeObjectURL(cached.renderUrl);
    snapshotCache.current.clear();
    snapshotRequests.current.clear();
  }, [run?.runId]);

  useEffect(() => {
    if (followLatest && frames.length) setSelectedIndex(frames.length - 1);
  }, [followLatest, frames.length]);

  const selected = frames[Math.min(selectedIndex, Math.max(frames.length - 1, 0))];
  const displayMode = fieldMode === "matlab" && !selected?.snapshot?.renderPath ? "density" : fieldMode;
  const currentIteration = finiteOrNull(selected?.iteration ?? run?.metrics.iteration);
  const progressPercent = currentIteration === null || maxIterations < 1
    ? null
    : Math.max(0, Math.min(100, currentIteration / maxIterations * 100));
  const isActive = run?.status === "queued" || run?.status === "running";
  const solverName = run?.lane === "python-fem" ? "Python FEM" : run?.lane === "compiled-runtime" ? "MATLAB Runtime" : "MATLAB";

  useEffect(() => {
    let cancelled = false;
    setSnapshotError("");
    if (!run?.runId || !selected?.snapshot) {
      setSnapshotLoading(false);
      return () => { cancelled = true; };
    }
    const snapshot = selected.snapshot;
    const readSnapshot = (descriptor: SnapshotDescriptor) => {
      const descriptorKey = `${run.runId}:${descriptor.densityPath}:${descriptor.stressPath || ""}:${descriptor.renderPath || ""}`;
      const cached = snapshotCache.current.get(descriptorKey);
      if (cached) return Promise.resolve(cached);
      const pending = snapshotRequests.current.get(descriptorKey);
      if (pending) return pending;
      const request = (async () => {
        const densityBuffer = await engineeringArtifactBuffer(run.runId, descriptor.densityPath);
        const densityRaw = readFloat32LittleEndian(densityBuffer);
        const densityVolume = asFortranVolume(densityRaw, descriptor.shape);
        let stress: number[][] = [];
        let stressVolume: MatlabVolume | null = null;
        if (descriptor.stressPath) {
          const stressBuffer = await engineeringArtifactBuffer(run.runId, descriptor.stressPath);
          const stressRaw = readFloat32LittleEndian(stressBuffer);
          stress = projectFortranVolume(stressRaw, descriptor.shape);
          stressVolume = asFortranVolume(stressRaw, descriptor.shape);
        }
        let renderUrl = "";
        if (descriptor.renderPath) {
          const renderBuffer = await engineeringArtifactBuffer(run.runId, descriptor.renderPath);
          renderUrl = URL.createObjectURL(new Blob([renderBuffer], { type: "image/png" }));
        }
        const value = {
          density: projectFortranVolume(densityRaw, descriptor.shape),
          stress,
          densityVolume,
          stressVolume,
          renderUrl,
        };
        snapshotCache.current.set(descriptorKey, value);
        return value;
      })();
      snapshotRequests.current.set(descriptorKey, request);
      void request.finally(() => snapshotRequests.current.delete(descriptorKey));
      return request;
    };
    const load = async () => {
      setSnapshotLoading(true);
      const value = await readSnapshot(snapshot);
      if (!cancelled) {
        setDensity(value.density);
        setStress(value.stress);
        setDensityVolume(value.densityVolume);
        setStressVolume(value.stressVolume);
        setRenderUrl(value.renderUrl);
      }
      const neighbors = [frames[selectedIndex - 1], frames[selectedIndex + 1]].filter(Boolean);
      neighbors.forEach(frame => { if (frame.snapshot) void readSnapshot(frame.snapshot).catch(() => undefined); });
    };
    void load()
      .catch(reason => { if (!cancelled) setSnapshotError(String(reason)); })
      .finally(() => { if (!cancelled) setSnapshotLoading(false); });
    return () => {
      cancelled = true;
    };
  }, [run?.runId, selected?.iteration, selected?.snapshot?.densityPath, selected?.snapshot?.stressPath, selected?.snapshot?.renderPath, selectedIndex, frames]);

  return <section className={"iteration-workspace" + (compact ? " compact" : "")} aria-label="迭代可视化">
    <header className="workspace-view-heading">
      <div><span className="view-kicker">REAL MATLAB ITERATION ARTIFACTS</span><h2>迭代时间轴</h2></div>
      <label className="follow-latest"><input type="checkbox" checked={followLatest} onChange={event => setFollowLatest(event.target.checked)}/><Radio size={13}/>跟随最新</label>
    </header>
    <div className="iteration-stage">
      <section className="iteration-canvas">
        <div className="canvas-label">
          <span><Activity size={14}/>{displayMode === "matlab" ? "MATLAB 原始迭代图" : displayMode === "density" ? "真实密度快照" : "真实 Von Mises 应力快照"}</span>
          <span className="field-switch">
            <button className={displayMode === "matlab" ? "active" : ""} disabled={!renderUrl} onClick={() => setFieldMode("matlab")}>MATLAB 原图</button>
            <button className={displayMode === "density" ? "active" : ""} disabled={!density.length} onClick={() => setFieldMode("density")}>{selected?.snapshot?.dimension === "3d" ? "3D 密度" : "密度"}</button>
            <button className={displayMode === "stress" ? "active" : ""} disabled={!stress.length} onClick={() => setFieldMode("stress")}>{selected?.snapshot?.dimension === "3d" ? "3D 应力" : "应力"}</button>
          </span>
        </div>
        {snapshotLoading && !density.length && !renderUrl ? <div className="snapshot-loading-indicator" aria-label="正在加载真实快照"><RefreshCw className="spin" size={18}/></div> : null}
        {snapshotError && !density.length && !renderUrl ? <div className="view-empty"><Activity size={24}/><b>快照读取失败</b><span>{snapshotError}</span></div> : null}
        {displayMode === "matlab" && renderUrl ? <div className="iteration-real-frame matlab-render-frame">
          <img src={renderUrl} alt={`MATLAB 第 ${selected?.iteration} 轮真实 ${selected?.snapshot?.dimension.toUpperCase()} 拓扑迭代图`}/>
          <small>第 {selected?.iteration} 轮 · MATLAB 原始逐轮渲染 · SHA-256 {selected?.snapshot?.renderSha256?.slice(0, 12) || "—"}</small>
        </div> : null}
        {displayMode !== "matlab" && density.length ? <div className="iteration-real-frame">
          {selected?.snapshot?.dimension === "3d" && densityVolume
            ? <InteractiveVolumeView
                density={densityVolume}
                field={displayMode === "stress" && stressVolume ? stressVolume : densityVolume}
                mode={displayMode}
                viewState={volumeViewState}
                onViewStateChange={setVolumeViewState}
              />
            : <ScalarMap values={displayMode === "stress" ? stress : density} mode={displayMode}/>}
          <small>第 {selected?.iteration} 轮 · {selected?.snapshot?.dimension.toUpperCase()} · MATLAB float32/F-order 制品 · SHA-256 {(displayMode === "stress" ? selected?.snapshot?.stressSha256 : selected?.snapshot?.densitySha256)?.slice(0, 12) || "—"}</small>
        </div> : null}
        {(renderUrl || density.length || isActive) ? <div className="iteration-image-progress">
          <div className="iteration-progress-meta"><span>第 {currentIteration ?? 0} / {maxIterations} 轮 · 柔度 {selected?.compliance?.toFixed?.(4) ?? "—"} · 体积分数 {selected?.volumeFraction?.toFixed?.(4) ?? "—"} · 灰度率 {selected?.grayRatio?.toFixed?.(4) ?? run?.metrics.grayRatio?.toFixed?.(4) ?? "—"}</span><strong>{progressPercent === null ? "处理中" : `${Math.round(progressPercent)}%`}</strong></div>
          <div className={"iteration-progress-track" + (progressPercent === null ? " indeterminate" : "")} role="progressbar" aria-label="真实优化进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progressPercent === null ? undefined : Math.round(progressPercent)}>
            <i style={progressPercent === null ? undefined : { width: `${progressPercent}%` }}/>
          </div>
        </div> : null}
        {!snapshotLoading && !snapshotError && !density.length && !renderUrl ? <div className="iteration-live-status">
          {!run ? <div className="view-empty"><Activity size={24}/><b>启动优化后将在这里展示实时状态</b><span>运行产生真实进度或快照后会立即更新。</span></div> : null}
          {isActive ? <>
            <div className="iteration-live-heading"><Activity className="spin" size={22}/><div><b>{solverName} 优化{run.status === "queued" ? "正在排队" : "正在运行"}</b><span>{currentIteration === null ? "等待求解器报告首轮迭代" : `真实迭代 ${currentIteration} / ${maxIterations}`}</span></div></div>
            {latestConsole ? <pre className="iteration-console-line">{latestConsole}</pre> : null}
          </> : null}
          {run?.status === "completed" ? <div className="view-empty"><CheckCircle2 size={24}/><b>优化已经完成</b><span>当前运行未产生可显示的真实迭代快照，请在结果或制品中检查求解输出。</span></div> : null}
          {run?.status === "failed" ? <div className="view-empty"><Activity size={24}/><b>优化运行失败</b><span>{run.error?.message || latestConsole || "请查看下方运行输出。"}</span></div> : null}
          {run?.status === "cancelled" ? <div className="view-empty"><Activity size={24}/><b>优化已取消</b><span>{latestConsole || "可以调整参数后重新运行。"}</span></div> : null}
        </div> : null}
      </section>
      <aside className="iteration-metrics">
        <Metric label="状态" value={run?.status ?? "idle"}/>
        <Metric label="迭代" value={selected?.iteration ?? run?.metrics.iteration ?? "—"}/>
        <Metric label="柔度" value={selected?.compliance}/>
        <Metric label="体积分数" value={selected?.volumeFraction}/>
        <Metric label="灰度率" value={selected?.grayRatio ?? run?.metrics.grayRatio}/>
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
      <span>{frames.length ? (selectedIndex + 1) + " / " + frames.length : "0 / 0"}</span>
    </div>
  </section>;
}

function Metric({ label, value }: { label: string; value: unknown }) {
  const display = typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : String(value ?? "—");
  return <div><small>{label}</small><b>{display}</b></div>;
}
