import type { BuiltInCase, SolverDimension } from "../../optimization-config";

const CASE_LABELS: Record<BuiltInCase, string> = {
  cantilever: "悬臂梁", MBB: "MBB 梁", simply_supported: "简支梁", "L-bracket": "L 型支架",
};

export default function CaseSchematic({ dimension, bcType }: { dimension: SolverDimension; bcType: BuiltInCase }) {
  const is3d = dimension === "3d";
  const loadX = bcType === "cantilever" ? 264 : bcType === "L-bracket" ? 225 : 160;
  const loadY = bcType === "cantilever" ? 122 : bcType === "L-bracket" ? 76 : 48;
  return <figure className="case-schematic" aria-label={dimension.toUpperCase() + " " + CASE_LABELS[bcType] + "工况示意图"}>
    <svg viewBox="0 0 320 190" role="img">
      <defs><marker id="load-arrow" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#d65252"/></marker><pattern id="support-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#57728d" strokeWidth="2"/></pattern></defs>
      {bcType === "L-bracket" ? <path d={is3d ? "M58 32 H238 L265 50 V88 H145 V157 H58 Z" : "M58 32 H238 V88 H145 V157 H58 Z"} className="domain-shape"/> : <path d={is3d ? "M52 48 L259 48 L282 66 L282 135 L75 135 L52 117 Z" : "M52 48 H268 V135 H52 Z"} className="domain-shape"/>}
      {is3d ? <><path d="M52 48 L75 66 H282" className="depth-line"/><path d="M75 66 V135" className="depth-line"/></> : null}
      {bcType === "cantilever" || bcType === "L-bracket" ? <><rect x="42" y="38" width="10" height="110" fill="url(#support-hatch)"/><line x1="52" y1="39" x2="52" y2="148" className="support-line"/></> : null}
      {bcType === "MBB" ? <><path d="M58 136 l-10 16 h20 Z" className="support"/><circle cx="260" cy="148" r="8" className="roller"/><line x1="246" y1="158" x2="276" y2="158" className="support-line"/></> : null}
      {bcType === "simply_supported" ? <><path d="M68 136 l-10 16 h20 Z" className="support"/><circle cx="252" cy="148" r="8" className="roller"/><line x1="238" y1="158" x2="268" y2="158" className="support-line"/></> : null}
      <line x1={loadX} y1={loadY - 30} x2={loadX} y2={loadY} className="load-line" markerEnd="url(#load-arrow)"/><text x={loadX + 8} y={loadY - 15} className="load-label">F</text>
      <text x="160" y="178" textAnchor="middle" className="domain-label">{dimension.toUpperCase()} · {CASE_LABELS[bcType]} · 设计域 / 支撑 / 载荷</text>
    </svg>
  </figure>;
}
