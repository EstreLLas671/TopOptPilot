import { useEffect, useState } from "react";
import { ArrowLeft, Database, Gauge, Globe2, LoaderCircle, RefreshCw, Save, ShieldCheck, Terminal } from "lucide-react";
import { api } from "./api";
import type { AppSettings, SettingsDiagnostics } from "./types";
import "./settings.css";

type Props = { settings: AppSettings; onClose: () => void; onSaved: (value: AppSettings) => void };
const bytes = (value?: number) => value === undefined ? "—" : `${(value / 1024 / 1024).toFixed(1)} MB`;

export default function SettingsWorkspace({ settings, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState(settings), [tab, setTab] = useState("general");
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState(""), [diagnostics, setDiagnostics] = useState<SettingsDiagnostics | null>(null);
  const zh = draft.locale === "zh-CN"; const l = (cn:string, en:string) => zh ? cn : en;
  useEffect(() => setDraft(settings), [settings]);
  const update = (path: string, value: unknown) => setDraft(current => {
    const next = structuredClone(current) as Record<string, any>; let cursor: Record<string, any> = next;
    const parts = path.split("."); parts.slice(0, -1).forEach(key => cursor = cursor[key]); cursor[parts.at(-1)!] = value; return next as AppSettings;
  });
  const save = async () => { setBusy(true); try { const value = await api.saveSettings(draft); onSaved(value); setNotice(l("已保存。新研究默认值不会修改已有研究。", "Saved. New-research defaults do not modify existing research.")); } catch (e) { setNotice(String(e)); } finally { setBusy(false); } };
  const action = async (kind:"agent"|"pi"|"matlab"|"diagnostics"|"cache") => { setBusy(true); try {
    const result = kind === "agent" ? await api.testAgent() : kind === "pi" ? await api.restartPi() : kind === "matlab" ? await api.restartMatlab() : kind === "diagnostics" ? await api.diagnostics() : await api.clearCache();
    if (kind === "diagnostics") setDiagnostics(result as SettingsDiagnostics); setNotice(typeof result === "object" ? JSON.stringify(result) : String(result));
  } catch (e) { setNotice(String(e)); } finally { setBusy(false); } };
  const field = (label:string, path:string, type="text") => <label className="settings-field">{label}<input type={type} value={String(path.split(".").reduce((a:any,k)=>a?.[k],draft) ?? "")} onChange={e=>update(path,type==="number"?Number(e.target.value):e.target.value)}/></label>;
  return <div className="settings-workspace">
    <header className="settings-title"><button onClick={onClose}><ArrowLeft/> {l("返回工作台","Back to workspace")}</button><div><b>TopOptPilot {l("设置中心","Settings")}</b><small>{l("全局默认值只影响后续新建 Research","Global defaults affect only future Research")}</small></div><button className="approve" disabled={busy} onClick={save}>{busy?<LoaderCircle className="spin"/>:<Save/>}{l("保存设置","Save settings")}</button></header>
    <aside className="settings-nav">{[["general",<Globe2/>,l("通用","General")],["agent",<Terminal/>,l("Agent 与模型","Agent & model")],["compute",<Gauge/>,l("MATLAB 与计算","MATLAB & compute")],["defaults",<ShieldCheck/>,l("新研究默认值","New research defaults")],["data",<Database/>,l("数据与诊断","Data & diagnostics")]].map(([key,icon,label])=><button key={key as string} className={tab===key?"active":""} onClick={()=>setTab(key as string)}>{icon}{label}</button>)}</aside>
    <main className="settings-content">
      {tab==="general" && <section><h1>通用</h1><div className="settings-grid"><label className="settings-field">默认语言<select value={draft.locale} onChange={e=>update("locale",e.target.value)}><option value="zh-CN">中文</option><option value="en-US">English</option></select></label><label className="settings-field">界面密度<select value={draft.ui_density} onChange={e=>update("ui_density",e.target.value)}><option value="compact">紧凑</option><option value="standard">标准</option><option value="comfortable">舒展</option></select></label><label className="settings-field">启动行为<select value={draft.startup_behavior} onChange={e=>update("startup_behavior",e.target.value)}><option value="resume_last">恢复上次研究</option><option value="research_list">打开研究列表</option></select></label></div><p>桌面 sidecar：本机受令牌保护。版本 5.1.1；更新检查将在发布渠道接入后启用。</p></section>}
      {tab==="agent" && <section><h1>Agent 与模型</h1><p>DashScope API Key：{draft.api_key_status==="environment"?"已从环境变量检测到":"未配置"}。密钥不会显示、保存或写入报告。</p><div className="settings-grid">{field("默认模型","agent.model")}{field("Base URL","agent.base_url")}{field("请求超时（秒）","agent.timeout_seconds","number")}{field("自动重试次数","agent.max_retries","number")}<label className="settings-check"><input type="checkbox" checked={draft.agent.safe_mode} onChange={e=>update("agent.safe_mode",e.target.checked)}/>启用 Safe Mode</label></div><button onClick={()=>action("agent")}>测试连接</button><button onClick={()=>action("pi")}><RefreshCw/>重启所有 Pi 会话</button><p>保存 Agent 设置后，新会话生效；重启 Pi 会话可立即应用。</p></section>}
      {tab==="compute" && <section><h1>MATLAB 与计算</h1><div className="settings-grid">{field("MATLAB 根目录（R2024a）","compute.matlab_root")}{field("Python FEM 并发数","compute.python_workers","number")}{field("MATLAB 默认超时（秒）","compute.matlab_timeout_seconds","number")}{field("MATLAB 自动重试次数","compute.matlab_retry_count","number")}</div><button onClick={()=>action("matlab")}><RefreshCw/>重启受控 MATLAB MCP</button><p className="warning">F3 只允许真实 MATLAB MCP。任何设置都不能启用 Python fallback。</p></section>}
      {tab==="defaults" && <section><h1>新研究默认值</h1><p>不会修改任何已有 Research、实验、决策或复现包。</p><div className="settings-grid">{field("默认模式","new_research.mode")}{field("总预算","new_research.budget_total","number")}{field("F0 预算","new_research.budgets.f0","number")}{field("F1 预算","new_research.budgets.f1","number")}{field("F2 预算","new_research.budgets.f2","number")}{field("F3 预算","new_research.budgets.f3","number")}{field("材料 E","new_research.material.E","number")}{field("泊松比 nu","new_research.material.nu","number")}</div></section>}
      {tab==="data" && <section><h1>数据与诊断</h1>{field("下次启动使用的新数据目录","data.next_data_dir")}<p>不会自动迁移旧数据；保存后重启应用生效。</p><button onClick={()=>action("diagnostics")}>刷新只读诊断快照</button><button onClick={()=>action("cache")}>清理可再生缓存</button><p>清理不会删除 Research 记录或原始 MATLAB 证据。</p>{diagnostics&&<pre className="diagnostics">数据：{diagnostics.data_dir}{"\n"}数据库：{diagnostics.database}{"\n"}缓存：{bytes(diagnostics.cache_bytes)} · 可用磁盘：{bytes(diagnostics.free_disk_bytes)}{"\n"}{JSON.stringify(diagnostics.health,null,2)}</pre>}</section>}
      {notice&&<div className="settings-notice">{notice}</div>}
    </main>
  </div>;
}
