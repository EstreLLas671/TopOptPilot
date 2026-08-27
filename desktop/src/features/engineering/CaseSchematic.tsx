import { useEffect, useState } from "react";
import type { BuiltInCase, SolverDimension } from "../../optimization-config";
import { asFortranVolume, readFloat32LittleEndian, type MatlabVolume } from "./matlab-artifact";
import InteractiveVolumeView from "./InteractiveVolumeView";
type PreviewEntry = { dimension: SolverDimension; bcType: BuiltInCase; shape: number[]; densityPath: string; stressPath?: string; renderPath?: string; source?: string; configDigest?: string };
type PreviewManifest = { cases: PreviewEntry[] };
const labels: Record<BuiltInCase, string> = { cantilever: "悬臂梁", MBB: "MBB 梁", simply_supported: "简支梁", "L-bracket": "L 型支架" };
function baseUrl(path: string) { return `/case-previews/${path.replace(/^\//, "")}`; }
function TwoDPreview({ density }: { density: MatlabVolume }) {
  const [rows, cols] = density.shape;
  return <div className="case-preview-2d" role="img" aria-label="MATLAB 二维密度案例预览">
    <div className="case-preview-grid" style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}>{Array.from({ length: rows * cols }, (_, index) => { const row = index % rows; const col = Math.floor(index / rows); const at = row + rows * col; const d = density.values[at]; return <span key={index} style={{ opacity: d < .05 ? .04 : .25 + .75 * Math.min(1, d), background: `hsl(${210 - 22 * d} 68% ${88 - 45 * d}%)` }} />; })}</div>
  </div>;
}

export default function CaseSchematic({ dimension, bcType }: { dimension: SolverDimension; bcType: BuiltInCase }) {
  const [manifest, setManifest] = useState<PreviewManifest | null>(null);
  const [data, setData] = useState<{ density: MatlabVolume } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${dimension}:${bcType}`;
  useEffect(() => {
    let active = true;
    fetch(baseUrl("manifest.json")).then(r => r.ok ? r.json() : Promise.reject()).then(v => { if (active) setManifest(v); }).catch(() => { if (active) setError("案例预览不可用"); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    const entry = manifest?.cases?.find(item => `${item.dimension}:${item.bcType}` === key);
    if (!entry) { if (manifest) setError("案例预览不可用"); return; }
    let active = true;
    setError(null);
    fetch(baseUrl(entry.densityPath)).then(r => r.ok ? r.arrayBuffer() : Promise.reject()).then(buffer => {
      if (active) setData({ density: asFortranVolume(readFloat32LittleEndian(buffer), entry.shape) });
    }).catch(() => { if (active) setError("案例预览不可用"); });
    return () => { active = false; };
  }, [key, manifest]);
  const title = `${dimension.toUpperCase()} · ${labels[bcType]}`;
  if (error) return <figure className="case-schematic case-preview-unavailable"><figcaption>{title}</figcaption><div>{error}</div></figure>;
  if (!data) return <figure className="case-schematic case-preview-unavailable"><figcaption>{title}</figcaption><div>正在加载 MATLAB 案例</div></figure>;
  return <figure className="case-schematic case-preview-real">
    <figcaption><span>{title}</span></figcaption>
    <section className="case-preview-section case-preview-result">{dimension === "3d" ? <InteractiveVolumeView density={data.density} field={data.density} mode="density" surfaceOnly/> : <TwoDPreview density={data.density}/>}</section>
  </figure>;
}