import { useEffect, useMemo, useState } from "react";
import { Activity, CheckCircle2, Radio, RefreshCw } from "lucide-react";
import { engineeringArtifactBuffer } from "../../backend-artifact";
import type { EngineeringRun } from "../../types";
import { projectFortranVolume, readFloat32LittleEndian } from "./matlab-artifact";
import { ScalarMap } from "./ResultViewer";

type SnapshotDescriptor = {
  densityPath: string;
  stressPath: string | null;
  shape: number[];
  dimension: "2d" | "3d";
  densitySha256?: string;
  stressSha256?: string;
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
    shape,
    dimension: raw.dimension === "2d" ? "2d" : "3d",
    densitySha256: typeof raw.densitySha256 === "string" ? raw.densitySha256 : undefined,
    stressSha256: typeof raw.stressSha256 === "string" ? raw.stressSha256 : undefined,
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
  const [fieldMode, setFieldMode] = useState<"density" | "stress">("density");
  const [density, setDensity] = useState<number[][]>([]);
  const [stress, setStress] = useState<number[][]>([]);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  useEffect(() => {
    if (followLatest && frames.length) setSelectedIndex(frames.length - 1);
  }, [followLatest, frames.length]);

  const selected = frames[Math.min(selectedIndex, Math.max(frames.length - 1, 0))];

  useEffect(() => {
    let cancelled = false;
    setDensity([]);
    setStress([]);
    setFieldMode("density");
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
      if (!cancelled) {
        setDensity(densityValues);
        setStress(stressValues);
      }
    };
    void load()
      .catch(reason => { if (!cancelled) setSnapshotError(String(reason)); })
      .finally(() => { if (!cancelled) setSnapshotLoading(false); });
    return () => { cancelled = true; };
  }, [run?.runId, selected?.iteration, selected?.snapshot?.densityPath, selected?.snapshot?.stressPath]);

  return <section className="iteration-workspace" aria-label="迭代可视化">
    <header className="workspace-view-heading">
      <div><span className="view-kicker">REAL MATLAB ITERATION ARTIFACTS</span><h2>迭代时间轴</h2></div>
      <label className="follow-latest"><input type="checkbox" checked={followLatest} onChange={event => setFollowLatest(event.target.checked)}/><Radio size={13}/>跟随最新</label>
    </header>
    <div className="iteration-stage">
      <section className="iteration-canvas">
        <div className="canvas-label">
          <span><Activity size={14}/>{fieldMode === "density" ? "真实密度快照" : "真实 Von Mises 应力快照"}</span>
          <span className="field-switch">
            <button className={fieldMode === "density" ? "active" : ""} disabled={!density.length} onClick={() => setFieldMode("density")}>密度</button>
            <button className={fieldMode === "stress" ? "active" : ""} disabled={!stress.length} onClick={() => setFieldMode("stress")}>应力</button>
          </span>
        </div>
        {snapshotLoading ? <div className="view-empty"><RefreshCw className="spin" size={24}/><b>正在校验并读取 MATLAB 快照</b></div> : null}
        {!snapshotLoading && snapshotError ? <div className="view-empty"><Activity size={24}/><b>快照读取失败</b><span>{snapshotError}</span></div> : null}
        {!snapshotLoading && !snapshotError && density.length ? <div className="iteration-real-frame">
          <ScalarMap values={fieldMode === "stress" ? stress : density} mode={fieldMode}/>
          <small>第 {selected?.iteration} 轮 · {selected?.snapshot?.dimension.toUpperCase()} · MATLAB float32/F-order 制品 · SHA-256 {selected?.snapshot?.densitySha256?.slice(0, 12) || "校验中"}</small>
        </div> : null}
        {!snapshotLoading && !snapshotError && !density.length ? <div className="view-empty"><Activity size={24}/><b>等待真实 MATLAB 迭代快照</b><span>只有 MATLAB 写入完整密度帧并登记 SHA-256 后才会显示，不生成占位结果。</span></div> : null}
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