import { useState } from "react";
import { RefreshCw, X } from "lucide-react";
import type { BackendComponent, SystemHealth } from "./types";

const order = [["pi_rpc","Pi RPC"],["qwen_api","Qwen API"],["matlab_2d","MATLAB 2D"],
  ["matlab_3d","MATLAB 3D"],["matlab_mcp","MATLAB MCP"],["matlab","MATLAB"],["sidecar","Sidecar"]];
const className = (status:string) => status.toLowerCase().replaceAll("_","-");

export default function HealthBar({health,onRefresh}:{health:SystemHealth|null;onRefresh:()=>void}) {
  const [selected,setSelected]=useState<[string,BackendComponent]|null>(null);
  return <div className="backend-health">
    {order.map(([key,label])=>{const item=health?.components?.[key];const status=item?.status||"STARTING";return <button key={key} onClick={()=>item&&setSelected([label,item])} title={`${label}: ${status}`}><i className={`health-dot health-${className(status)}`}/><span>{label}</span><em>{status}</em></button>})}
    <button className="health-refresh" onClick={onRefresh}><RefreshCw/></button>
    {selected&&<div className="health-popover"><header><b>{selected[0]}</b><button onClick={()=>setSelected(null)}><X/></button></header><span className={`status status-${className(selected[1].status)}`}>{selected[1].status}</span><dl>{Object.entries(selected[1]).filter(([key,value])=>key!=="status"&&value!=null&&typeof value!=="object").map(([key,value])=><div key={key}><dt>{key}</dt><dd>{String(value)}</dd></div>)}</dl>{selected[1].last_error&&<p>{selected[1].last_error}</p>}</div>}
  </div>;
}
