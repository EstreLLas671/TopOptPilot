import { useEffect, useMemo, useState } from "react";
import { Activity, CheckCircle2, Radio, RefreshCw } from "lucide-react";
import { engineeringArtifactBuffer } from "../../backend-artifact";
import type { EngineeringRun } from "../../types";
import { projectFortranVolume, readFloat32LittleEndian } from "./matlab-artifact";
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
      snapshot: snapshotFrom(event.snapshot),
    }];
  }), [events]);
  const [followLatest, setFollowLatest] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [fieldMode, setFieldMode] = useState<"matlab" | "density" | "stress">("matlab");
  const [density, setDensity] = useState<number[][]>([]);
  const [stress, setStress] = useState<number[][]>([]);
  const [renderUrl, setRenderUrl] = useState("");
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  useEffect(() => {
    if (followLatest && frames.length) setSelectedIndex(frames.length - 1);
  }, [followLatest, frames.length]);

  const selected = frames[Math.min(selectedIndex, Math.max(frames.length - 1, 0))];
  const displayMode = fieldMode === "matlab" && !selected?.snapshot?.renderPath ? "density" : fieldMode;

  useEffect(() => {
    let cancelled = false;
    let renderObjectUrl: string | null = null;
    setDensity([]);
    setStress([]);
    setRenderUrl("");
    setSnapshotError("");
    if (!run?.runId || !selected?.snapshot) {
      setSnapshotLoading(false);
      return () => { cancelled = true; };
    }
    const load = async () => {
      setSnapshotLoading(true);
      const densityBuffer = await engineeringArtifactBuffer(run.runId, selected.snapshot!.densityPath);
      const densityValues = projectFortranVolume(
        readFloat32LittleEndian(densityBuffer),
        selected.snapshot!.shape,
      );
      let stressValues: number[][] = [];
      if (selected.snapshot!.stressPath) {
        const stressBuffer = await engineeringArtifactBuffer(run.runId, selected.snapshot!.stressPath);
        stressValues = projectFortranVolume(
          readFloat32LittleEndian(stressBuffer),
          selected.snapshot!.shape,
        );
      }
      if (selected.snapshot!.renderPath) {
        const renderBuffer = await engineeringArtifactBuffer(run.runId, selected.snapshot!.renderPath);
        renderObjectUrl = URL.createObjectURL(new Blob([renderBuffer], { type: "image/png" }));
      }
      if (!cancelled) {
        setDensity(densityValues);
        setStress(stressValues);
        setRenderUrl(renderObjectUrl || "");
      } else if (renderObjectUrl) {
        URL.revokeObjectURL(renderObjectUrl);
      }
    };
    void load()
      .catch(reason => { if (!cancelled) setSnapshotError(String(reason)); })
      .finally(() => { if (!cancelled) setSnapshotLoading(false); });
    return () => {
      cancelled = true;
      if (renderObjectUrl) URL.revokeObjectURL(renderObjectUrl);
    };
  }, [run?.runId, selected?.iteration, selected?.snapshot?.densityPath, selected?.snapshot?.stressPath, selected?.snapshot?.renderPath]);

  return <section className="iteration-workspace" aria-label="迭代可视化">
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
            <button className={displayMode === "density" ? "active" : ""} disabled={!density.length} onClick={() => setFieldMode("density")}>密度</button>
            <button className={displayMode === "stress" ? "active" : ""} disabled={!stress.length} onClick={() => setFieldMode("stress")}>应力</button>
          </span>
        </div>
        {snapshotLoading ? <div className="view-empty"><RefreshCw className="spin" size={24}/><b>正在校验并读取 MATLAB 快照</b></div> : null}
        {!snapshotLoading && snapshotError ? <div className="view-empty"><Activity size={24}/><b>快照读取失败</b><span>{snapshotError}</span></div> : null}
        {!snapshotLoading && !snapshotError && displayMode === "matlab" && renderUrl ? <div className="iteration-real-frame matlab-render-frame">
          <img src={renderUrl} alt={`MATLAB 第 ${selected?.iteration} 轮真实 ${selected?.snapshot?.dimension.toUpperCase()} 拓扑迭代图`}/>
          <small>第 {selected?.iteration} 轮 · MATLAB 原始逐轮渲染 · SHA-256 {selected?.snapshot?.renderSha256?.slice(0, 12) || "校验中"}</small>
        </div> : null}
        {!snapshotLoading && !snapshotError && displayMode !== "matlab" && density.length ? <div className="iteration-real-frame">
          <ScalarMap values={displayMode === "stress" ? stress : density} mode={displayMode}/>
          <small>第 {selected?.iteration} 轮 · {selected?.snapshot?.dimension.toUpperCase()} · MATLAB float32/F-order 制品 · SHA-256 {(displayMode === "stress" ? selected?.snapshot?.stressSha256 : selected?.snapshot?.densitySha256)?.slice(0, 12) || "校验中"}</small>
        </div> : null}
        {!snapshotLoading && !snapshotError && !density.length && !renderUrl ? <div className="view-empty"><Activity size={24}/><b>等待真实 MATLAB 迭代快照</b><span>每轮 MATLAB 原图、密度帧完成并登记 SHA-256 后会立即显示，不生成占位结果。</span></div> : null}
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
      <span>{frames.length ? (selectedIndex + 1) + " / " + frames.length : "0 / 0"}</span>
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