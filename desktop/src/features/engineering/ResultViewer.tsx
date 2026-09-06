import { useEffect, useMemo, useRef, useState } from "react";
import { FileJson2, Gauge, RefreshCw } from "lucide-react";
import { engineeringArtifactBuffer } from "../../backend-artifact";
import { engineeringArtifactText } from "../../backend-text";
import type { EngineeringArtifactRef, EngineeringRun } from "../../types";
import { parseDensityCsv, parseHistoryJson, type ConvergencePoint } from "./artifact-viewer";
import { asFortranVolume, projectFortranVolume, readFloat32LittleEndian, type MatlabVolume } from "./matlab-artifact";
import InteractiveVolumeView, { type ViewState } from "./InteractiveVolumeView";

type Props = { run: EngineeringRun | null; onError: (message: string) => void };
type FieldMode = "density" | "stress";
type MatlabManifest = { shape: number[]; density_file: string; stress_file?: string };
type LoadedRunResult = {
  density: number[][];
  stress: number[][];
  densityVolume: MatlabVolume | null;
  stressVolume: MatlabVolume | null;
  dimension: "2d" | "3d";
  history: ConvergencePoint[];
};

const resultDataCache = new Map<string, Promise<LoadedRunResult>>();

function cachedRunResult(run: EngineeringRun): Promise<LoadedRunResult> {
  const densityRef = run.files.find(item => item.relativePath === "density.csv");
  const historyRef = run.files.find(item => item.relativePath === "history.json");
  const manifestRef = run.files.find(item => item.relativePath === "result_manifest.json");
  const version = [manifestRef, densityRef, historyRef].map(item => item?.sha256 || "none").join(":");
  const key = `${run.runId}:${version}`;
  const existing = resultDataCache.get(key);
  if (existing) return existing;
  const pending = (async () => {
    if (!manifestRef && !densityRef) {
      throw new Error("运行已完成，但最终结果索引尚未就绪。请稍后重试。");
    }
    const [manifestText, densityText, historyText] = await Promise.all([
      manifestRef ? engineeringArtifactText(run.runId, manifestRef.relativePath) : Promise.resolve(""),
      densityRef ? engineeringArtifactText(run.runId, densityRef.relativePath) : Promise.resolve(""),
      historyRef ? engineeringArtifactText(run.runId, historyRef.relativePath) : Promise.resolve("[]"),
    ]);
    const manifest = manifestText ? JSON.parse(manifestText) as MatlabManifest : null;
    let density = densityText.trim() ? parseDensityCsv(densityText) : [];
    let stress: number[][] = [];
    let densityVolume: MatlabVolume | null = null;
    let stressVolume: MatlabVolume | null = null;
    const dimension: "2d" | "3d" = manifest?.shape.length === 3 ? "3d" : "2d";
    if (manifest) {
      const [densityBuffer, stressBuffer] = await Promise.all([
        engineeringArtifactBuffer(run.runId, manifest.density_file),
        manifest.stress_file ? engineeringArtifactBuffer(run.runId, manifest.stress_file) : Promise.resolve(null),
      ]);
      const densityRaw = readFloat32LittleEndian(densityBuffer);
      if (dimension === "3d") densityVolume = asFortranVolume(densityRaw, manifest.shape);
      else density = projectFortranVolume(densityRaw, manifest.shape);
      if (stressBuffer) {
        const stressRaw = readFloat32LittleEndian(stressBuffer);
        if (dimension === "3d") stressVolume = asFortranVolume(stressRaw, manifest.shape);
        else stress = projectFortranVolume(stressRaw, manifest.shape);
      }
    }
    return { density, stress, densityVolume, stressVolume, dimension, history: parseHistoryJson(historyText) };
  })();
  if (resultDataCache.size >= 4) {
    const oldest = resultDataCache.keys().next().value;
    if (oldest) resultDataCache.delete(oldest);
  }
  resultDataCache.set(key, pending);
  pending.catch(() => resultDataCache.delete(key));
  return pending;
}

export function ScalarMap({ values, mode }: { values: number[][]; mode: FieldMode }) {
  const cells = values.flat();
  const [minimum, maximum] = cells.length ? [Math.min(...cells), Math.max(...cells)] : [0, 1];
  const span = Math.max(maximum - minimum, 1e-12);
  if (!cells.length) return <div className="artifact-empty">本次运行没有可渲染的{mode === "density" ? "密度" : "应力"}场。</div>;
  const cols = values[0].length, rows = values.length;
  return <div className={`density-map ${mode}`} style={{ gridTemplateColumns: `repeat(${cols}, minmax(2px, 1fr))`, aspectRatio: `${cols} / ${rows}`, width: "100%", height: "auto", maxHeight: "100%", minHeight: 0, flex: "0 0 auto", alignSelf: "center", margin: "0 auto" }} aria-label={mode === "density" ? "密度场" : "Von Mises 应力场"}>
    {cells.map((value, index) => {
      const normalized = (value - minimum) / span;
      const color = mode === "density"
        ? `rgb(${Math.round(241 - normalized * 178)}, ${Math.round(247 - normalized * 112)}, ${Math.round(252 - normalized * 48)})`
        : `hsl(${Math.round(220 - normalized * 220)} 78% ${Math.round(78 - normalized * 32)}%)`;
      return <span key={index} title={value.toPrecision(5)} style={{ background: color }}/>;
    })}
  </div>;
}

export function ConvergenceChart({ points }: { points: ConvergencePoint[] }) {
  const chart = useMemo(() => {
    if (!points.length) return null;
    const values = points.map(point => point.compliance);
    const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, 1e-9);
    const x0 = 72, x1 = 490, y0 = 24, y1 = 202;
    const polyline = points.map((point, index) => {
      const x = x0 + (index / Math.max(points.length - 1, 1)) * (x1 - x0);
      const y = y1 - ((point.compliance - min) / span) * (y1 - y0);
      return `${x},${y}`;
    }).join(" ");
    return { polyline, min, max, first: points[0].iteration, last: points.at(-1)?.iteration ?? points.length };
  }, [points]);
  if (!chart) return <div className="artifact-empty">尚无收敛历史。</div>;
  return <svg className="convergence-chart" viewBox="0 0 520 250" preserveAspectRatio="xMidYMid meet" aria-label="柔度收敛曲线">
    <path d="M72 24V202H490 M72 113H490" className="chart-grid"/>
    <path d="M72 24V202H490" className="chart-axis"/>
    <polyline points={chart.polyline} fill="none" className="chart-line"/>
    <text x="64" y="30" textAnchor="end" className="chart-tick">{chart.max.toFixed(2)}</text>
    <text x="64" y="207" textAnchor="end" className="chart-tick">{chart.min.toFixed(2)}</text>
    <text x="72" y="224" textAnchor="middle" className="chart-tick">{chart.first}</text>
    <text x="490" y="224" textAnchor="middle" className="chart-tick">{chart.last}</text>
    <text x="281" y="244" textAnchor="middle" className="chart-label">迭代</text>
    <text x="18" y="113" textAnchor="middle" transform="rotate(-90 18 113)" className="chart-label">柔度</text>
  </svg>;
}

export default function ResultViewer({ run, onError }: Props) {
  const onErrorRef = useRef(onError);
  const [density, setDensity] = useState<number[][]>([]);
  const [stress, setStress] = useState<number[][]>([]);
  const [densityVolume, setDensityVolume] = useState<MatlabVolume | null>(null);
  const [stressVolume, setStressVolume] = useState<MatlabVolume | null>(null);
  const [dimension, setDimension] = useState<"2d" | "3d">("2d");
  const [viewState, setViewState] = useState<ViewState>({ rotationX: -0.52, rotationY: 0.72, zoom: 1 });
  const [fieldMode, setFieldMode] = useState<FieldMode>("density");
  const [history, setHistory] = useState<ConvergencePoint[]>([]);
  const [selected, setSelected] = useState<EngineeringArtifactRef | null>(null);
  const [preview, setPreview] = useState("");
  const [loading, setLoading] = useState(false);
  const [resultLoading, setResultLoading] = useState(false);
  const [resultLoadError, setResultLoadError] = useState("");
  const [retryNonce, setRetryNonce] = useState(0);
  const resultVersion = useMemo(() => (run?.files || [])
    .map(item => `${item.relativePath}:${item.sha256}`)
    .sort()
    .join("|"), [run?.files]);

  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  async function readArtifact(artifact: EngineeringArtifactRef) {
    if (!run) return;
    setSelected(artifact);
    if (/float32|octet-stream|matlab\.mat/.test(artifact.mediaType)) {
      setPreview(`二进制制品\n路径：${artifact.relativePath}\n大小：${artifact.sizeBytes} bytes\nSHA-256：${artifact.sha256}`);
      return;
    }
    setLoading(true);
    try { setPreview((await engineeringArtifactText(run.runId, artifact.relativePath)).slice(0, 120_000)); }
    catch (reason) { onError(String(reason)); }
    finally { setLoading(false); }
  }

  useEffect(() => {
    let cancelled = false;
    setSelected(null); setPreview(""); setFieldMode("density"); setResultLoadError("");
    if (!run || run.status !== "completed") return () => { cancelled = true; };
    setResultLoading(true);
    const load = async () => {
      const loaded = await cachedRunResult(run);
      if (!cancelled) {
        setDensity(loaded.density); setStress(loaded.stress);
        setDensityVolume(loaded.densityVolume); setStressVolume(loaded.stressVolume);
        setDimension(loaded.dimension); setHistory(loaded.history);
      }
    };
    void load().catch(reason => {
      if (!cancelled) {
        const message = String(reason);
        setResultLoadError(message);
        onErrorRef.current(message);
      }
    }).finally(() => { if (!cancelled) setResultLoading(false); });
    return () => { cancelled = true; };
  }, [run?.runId, run?.status, resultVersion, retryNonce]);

  if (!run) return <div className="result-empty"><Gauge size={24}/><b>尚未运行工程求解</b><span>选择求解链路并启动后，真实密度、收敛历史与 provenance 会显示在这里。</span></div>;
  const show3d = dimension === "3d" && densityVolume !== null;
  return <div className="result-viewer">
    {resultLoading && !density.length && !densityVolume ? <div className="result-loading"><RefreshCw className="spin" size={16}/>正在读取真实结果制品…</div> : null}
    {resultLoadError ? <div className="result-load-error"><span>结果读取失败：{resultLoadError}</span><button className="outline-button" onClick={() => setRetryNonce(value => value + 1)}>重试</button></div> : null}
    <header className="result-summary"><div><small>Run ID</small><b>{run.runId}</b></div><div><small>链路 / 状态</small><b>{run.lane} · {run.status}</b></div><div><small>柔度</small><b>{run.metrics.compliance?.toFixed?.(4) ?? "—"}</b></div><div><small>体积分数</small><b>{run.metrics.volumeFraction?.toFixed?.(4) ?? "—"}</b></div><div><small>灰度率</small><b>{run.metrics.grayRatio?.toFixed?.(4) ?? "—"}</b></div></header>
    <div className="result-plots"><section><h4 className="field-heading"><span>{fieldMode === "density" ? "密度场" : "Von Mises 应力场"}</span><span className="field-switch"><button className={fieldMode === "density" ? "active" : ""} onClick={() => setFieldMode("density")}>密度</button><button className={fieldMode === "stress" ? "active" : ""} disabled={show3d ? !stressVolume : !stress.length} onClick={() => setFieldMode("stress")}>应力</button></span></h4>{show3d && densityVolume ? <InteractiveVolumeView density={densityVolume} field={fieldMode === "stress" && stressVolume ? stressVolume : densityVolume} mode={fieldMode} viewState={viewState} onViewStateChange={setViewState}/> : <ScalarMap values={fieldMode === "density" ? density : stress} mode={fieldMode}/>}</section><section><h4>柔度收敛</h4><ConvergenceChart points={history}/></section></div>
    <section className="artifact-browser"><header><span><FileJson2 size={14}/>制品与快照</span><small>SHA-256 校验引用 · {run.provenance.resultKind || "unknown"}</small></header><div className="artifact-list">{[...run.files, ...run.snapshots].map(item => <button key={`${item.relativePath}-${item.sha256}`} onClick={() => void readArtifact(item)} className={selected?.sha256 === item.sha256 ? "active" : ""}><span>{item.relativePath}</span><small>{(item.sizeBytes / 1024).toFixed(1)} KB · {item.sha256.slice(0, 12)}</small></button>)}</div><pre className="artifact-preview">{loading ? <RefreshCw className="spin"/> : preview || "选择 JSON、CSV、日志或快照查看真实内容。二进制制品只显示元信息。"}</pre></section>
  </div>;
}
