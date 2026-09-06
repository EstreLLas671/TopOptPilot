import { useEffect, useMemo, useState } from "react";
import { LoaderCircle, X } from "lucide-react";
import { api } from "../../api";
import type { Experiment, ResearchVisualizationManifest } from "../../types";
import { asFortranVolume, projectFortranVolume, readFloat32LittleEndian, type MatlabVolume } from "../engineering/matlab-artifact";
import InteractiveVolumeView, { type ViewState } from "../engineering/InteractiveVolumeView";
import { ConvergenceChart, ScalarMap } from "../engineering/ResultViewer";

type Props = {
  researchId:string;
  experiment:Experiment | null;
  onClose:()=>void;
};

const labels:Record<string,string> = {
  dimension:"维度", bc_type:"工况", bcType:"工况", nelx:"X 向网格", nely:"Y 向网格", nelz:"Z 向网格",
  volfrac:"体积分数", volume_fraction:"体积分数", penal:"惩罚因子", rmin:"滤波半径",
  max_iter:"最大迭代", min_iter:"最小迭代", filter_strategy:"滤波策略", accuracy:"精度",
  E:"杨氏模量", nu:"泊松比",
};

function display(value:unknown):string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return Object.entries(value as Record<string,unknown>).map(([key,item]) => `${key}: ${display(item)}`).join(" · ");
  return String(value);
}

export default function ResearchResultDialog({ researchId, experiment, onClose }:Props) {
  const [manifest,setManifest]=useState<ResearchVisualizationManifest|null>(null);
  const [density,setDensity]=useState<MatlabVolume|null>(null);
  const [stress,setStress]=useState<MatlabVolume|null>(null);
  const [field,setField]=useState<"density"|"stress">("density");
  const [view,setView]=useState<ViewState>({rotationX:-.52,rotationY:.72,zoom:1});
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);

  useEffect(()=>{
    if(!experiment){setManifest(null);setDensity(null);setStress(null);setError("");return;}
    let cancelled=false;
    setBusy(true);setError("");setField("density");
    Promise.all([
      api.researchVisualization(researchId,experiment.id),
      api.researchVisualizationField(researchId,experiment.id,"density"),
    ]).then(([nextManifest,buffer])=>{
      if(cancelled)return;
      setManifest(nextManifest);
      setDensity(asFortranVolume(readFloat32LittleEndian(buffer),nextManifest.shape));
    }).catch(reason=>{if(!cancelled)setError(String(reason));})
      .finally(()=>{if(!cancelled)setBusy(false);});
    return()=>{cancelled=true;};
  },[researchId,experiment?.id]);

  async function selectStress(){
    if(!experiment||!manifest?.hasStress)return;
    setField("stress");
    if(stress)return;
    setBusy(true);
    try{setStress(asFortranVolume(readFloat32LittleEndian(await api.researchVisualizationField(researchId,experiment.id,"stress")),manifest.shape));}
    catch(reason){setField("density");setError(String(reason));}
    finally{setBusy(false);}
  }

  const twoDimensional=useMemo(()=>{
    if(!density)return null;
    const source=field==="stress"&&stress?stress:density;
    return projectFortranVolume(source.values,source.shape);
  },[density,stress,field]);
  const history=useMemo(()=>(manifest?.history||[]).flatMap(item=>{
    const iteration=Number(item.iteration),compliance=Number(item.compliance);
    return Number.isFinite(iteration)&&Number.isFinite(compliance)?[{iteration,compliance}]:[];
  }),[manifest]);
  if(!experiment)return null;
  const metrics=manifest?.metrics;
  return <div className="suggestion-dialog-backdrop research-result-dialog-backdrop" role="presentation">
    <section className="research-result-dialog" role="dialog" aria-modal="true" aria-label="科研最终方案详情">
      <header><div><b>科研方案详情</b><small>{experiment.id} · {manifest?.fidelity||experiment.fidelity} · {manifest?.backend||experiment.backend}</small></div><button className="dialog-icon-button" aria-label="关闭科研方案详情" title="关闭" onClick={onClose}><X size={15}/></button></header>
      {busy&&!density?<div className="research-result-loading"><LoaderCircle className="spin"/>正在读取真实实验制品…</div>:null}
      {error?<div className="error-card">{error}</div>:null}
      {manifest&&density?<div className="research-result-dialog-body">
        <aside><h3>方案运行配置</h3><dl>{Object.entries(manifest.config).map(([key,value])=><div key={key}><dt>{labels[key]||key}（{key}）</dt><dd>{display(value)}</dd></div>)}</dl><h3>证据摘要</h3><p>{manifest.resultSource||"LIVE_REAL_RUN"} · {manifest.status}</p><p className="result-evidence-ids">{manifest.evidenceIds.join(" · ")||"—"}</p></aside>
        <main>
          <div className="research-result-metrics"><Metric label="柔度" value={metrics?.compliance}/><Metric label="体积分数" value={metrics?.volumeFraction}/><Metric label="灰度率" value={metrics?.grayRatio}/><Metric label="连通分量" value={metrics?.connectedComponents}/></div>
          <nav className="result-field-tabs"><button className={field==="density"?"active":""} onClick={()=>setField("density")}>真实密度</button>{manifest.hasStress?<button className={field==="stress"?"active":""} onClick={()=>void selectStress()}>真实应力</button>:null}</nav>
          <section className="research-result-visualization">
            {manifest.dimension==="3d"?<InteractiveVolumeView density={density} field={field==="stress"&&stress?stress:density} mode={field} viewState={view} onViewStateChange={setView}/>:<ScalarMap values={twoDimensional || []} mode={field}/>}
          </section>
          <section className="research-result-convergence"><h4>柔度收敛</h4><ConvergenceChart points={history}/></section>
        </main>
      </div>:null}
    </section>
  </div>;
}

function Metric({label,value}:{label:string;value:unknown}){
  return <div><small>{label}</small><b>{typeof value==="number"?value.toFixed(4):"—"}</b></div>;
}
