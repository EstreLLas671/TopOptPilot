import { useEffect, useMemo, useState } from "react";
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

export function ScalarMap({ values, mode }: { values: number[][]; mode: FieldMode }) {
  const cells = values.flat();
  const [minimum, maximum] = cells.length ? [Math.min(...cells), Math.max(...cells)] : [0, 1];
  const span = Math.max(maximum - minimum, 1e-12);
  if (!cells.length) return <div className="artifact-empty">本次运行没有可渲染的{mode === "density" ? "密度" : "应力"}场。</div>;
  return <div className={`density-map ${mode}`} style={{ gridTemplateColumns: `repeat(${values[0].length}, minmax(2px, 1fr))` }} aria-label={mode === "density" ? "密度场" : "Von Mises 应力场"}>
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
    const x0 = 14, x1 = 96, y0 = 7, y1 = 39;
    const polyline = points.map((point, index) => {
      const x = x0 + (index / Math.max(points.length - 1, 1)) * (x1 - x0);
      const y = y1 - ((point.compliance - min) / span) * (y1 - y0);
      return `${x},${y}`;
    }).join(" ");
    return { polyline, min, max, first: points[0].iteration, last: points.at(-1)?.iteration ?? points.length };
  }, [points]);
  if (!chart) return <div className="artifact-empty">尚无收敛历史。</div>;
  return <svg className="convergence-chart" viewBox="0 0 104 50" preserveAspectRatio="xMidYMid meet" aria-label="柔度收敛曲线">
    <path d="M14 7V39H96 M14 23H96" className="chart-grid"/>
    <path d="M14 7V39H96" className="chart-axis"/>
    <polyline points={chart.polyline} fill="none" className="chart-line"/>
    <text x="12" y="9" textAnchor="end" className="chart-tick">{chart.max.toFixed(2)}</text>
    <text x="12" y="40" textAnchor="end" className="chart-tick">{chart.min.toFixed(2)}</text>
    <text x="14" y="45" textAnchor="middle" className="chart-tick">{chart.first}</text>
    <text x="96" y="45" textAnchor="middle" className="chart-tick">{chart.last}</text>
    <text x="55" y="49" textAnchor="middle" className="chart-label">迭代</text>
    <text x="3" y="24" textAnchor="middle" transform="rotate(-90 3 24)" className="chart-label">柔度</text>
  </svg>;
}

export default function ResultViewer({ run, onError }: Props) {
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
    setDensity([]); setStress([]); setDensityVolume(null); setStressVolume(null); setDimension("2d"); setHistory([]); setSelected(null); setPreview(""); setFieldMode("density");
    if (!run || run.status !== "completed") return () => { cancelled = true; };
    const densityRef = run.files.find(item => item.relativePath === "density.csv");
    const historyRef = run.files.find(item => item.relativePath === "history.json");
    const manifestRef = run.files.find(item => item.relativePath === "result_manifest.json");
    const load = async () => {
      const [densityText, historyText] = await Promise.all([
        densityRef ? engineeringArtifactText(run.runId, densityRef.relativePath) : Promise.resolve(""),
        historyRef ? engineeringArtifactText(run.runId, historyRef.relativePath) : Promise.resolve("[]"),
      ]);
      let densityValues = densityText.trim() ? parseDensityCsv(densityText) : [];
      let stressValues: number[][] = [];
      if (manifestRef) {
        const manifest = JSON.parse(await engineeringArtifactText(run.runId, manifestRef.relativePath)) as MatlabManifest;
        const densityBuffer = await engineeringArtifactBuffer(run.runId, manifest.density_file);
        const densityRaw = readFloat32LittleEndian(densityBuffer);
        densityValues = projectFortranVolume(densityRaw, manifest.shape);
        if (manifest.stress_file) {
          const stressBuffer = await engineeringArtifactBuffer(run.runId, manifest.stress_file);
          stressValues = projectFortranVolume(readFloat32LittleEndian(stressBuffer), manifest.shape);
        }
      }
      if (!cancelled) {
        setDensity(densityValues); setStress(stressValues); setDimension(manifestRef ? (JSON.parse(await engineeringArtifactText(run.runId, manifestRef.relativePath)) as MatlabManifest).shape.length === 3 ? "3d" : "2d" : "2d");
        if (manifestRef) {
          const manifest = JSON.parse(await engineeringArtifactText(run.runId, manifestRef.relativePath)) as MatlabManifest;
          const densityBuffer = await engineeringArtifactBuffer(run.runId, manifest.density_file);
          setDensityVolume(asFortranVolume(readFloat32LittleEndian(densityBuffer), manifest.shape));
          if (manifest.stress_file) {
            const stressBuffer = await engineeringArtifactBuffer(run.runId, manifest.stress_file);
            setStressVolume(asFortranVolume(readFloat32LittleEndian(stressBuffer), manifest.shape));
          }
        }
        setHistory(parseHistoryJson(historyText));
      }
    };
    void load().catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [run?.runId, run?.status, onError]);

  if (!run) return <div className="result-empty"><Gauge size={24}/><b>尚未运行工程求解</b><span>选择求解链路并启动后，真实密度、收敛历史与 provenance 会显示在这里。</span></div>;
  const show3d = dimension === "3d" && densityVolume !== null;
  return <div className="result-viewer">
    <header className="result-summary"><div><small>Run ID</small><b>{run.runId}</b></div><div><small>链路 / 状态</small><b>{run.lane} · {run.status}</b></div><div><small>柔度</small><b>{run.metrics.compliance?.toFixed?.(4) ?? "—"}</b></div><div><small>体积分数</small><b>{run.metrics.volumeFraction?.toFixed?.(4) ?? "—"}</b></div><div><small>灰度率</small><b>{run.metrics.grayRatio?.toFixed?.(4) ?? "—"}</b></div></header>
    <div className="result-plots"><section><h4 className="field-heading"><span>{fieldMode === "density" ? "密度场" : "Von Mises 应力场"}</span><span className="field-switch"><button className={fieldMode === "density" ? "active" : ""} onClick={() => setFieldMode("density")}>密度</button><button className={fieldMode === "stress" ? "active" : ""} disabled={!stress.length || (show3d && !stressVolume)} onClick={() => setFieldMode("stress")}>应力</button></span></h4>{show3d && densityVolume ? <InteractiveVolumeView density={densityVolume} field={fieldMode === "stress" && stressVolume ? stressVolume : densityVolume} mode={fieldMode} viewState={viewState} onViewStateChange={setViewState}/> : <ScalarMap values={fieldMode === "density" ? density : stress} mode={fieldMode}/>}</section><section><h4>柔度收敛</h4><ConvergenceChart points={history}/></section></div>
    <section className="artifact-browser"><header><span><FileJson2 size={14}/>制品与快照</span><small>SHA-256 校验引用 · {run.provenance.resultKind || "unknown"}</small></header><div className="artifact-list">{[...run.files, ...run.snapshots].map(item => <button key={`${item.relativePath}-${item.sha256}`} onClick={() => void readArtifact(item)} className={selected?.sha256 === item.sha256 ? "active" : ""}><span>{item.relativePath}</span><small>{(item.sizeBytes / 1024).toFixed(1)} KB · {item.sha256.slice(0, 12)}</small></button>)}</div><pre className="artifact-preview">{loading ? <RefreshCw className="spin"/> : preview || "选择 JSON、CSV、日志或快照查看真实内容。二进制制品只显示元信息。"}</pre></section>
  </div>;
}
