import { useState } from "react";
import { Boxes, FileJson2, Globe2, Play, Send, Square, Terminal } from "lucide-react";
import type { EngineeringRun } from "../../types";

type BottomTab = "terminal" | "log" | "output" | "tools" | "artifacts" | "diagnostics" | "browser";

type Props = {
  terminalSession: string;
  terminalStatus: string;
  terminalCommand: string;
  terminalOutput: string[];
  events: Array<Record<string, unknown>>;
  run: EngineeringRun | null;
  browserUrl: string;
  browserOpen: boolean;
  matlabDiagnostic: string;
  runtimeDiagnostic: string;
  onTerminalCommandChange: (value: string) => void;
  onBrowserUrlChange: (value: string) => void;
  onStartTerminal: () => void;
  onStopTerminal: () => void;
  onSendTerminalCommand: () => void;
  onToggleBrowser: () => void;
  onNavigateBrowser: () => void;
};

const tabs: Array<{ id: BottomTab; label: string }> = [
  { id: "terminal", label: "MATLAB 终端" },
  { id: "log", label: "运行日志" },
  { id: "output", label: "输出" },
  { id: "tools", label: "工具调用" },
  { id: "artifacts", label: "制品" },
  { id: "diagnostics", label: "诊断" },
  { id: "browser", label: "受限浏览器" },
];

function eventLine(event: Record<string, unknown>): string {
  const type = String(event.type || event.kind || "event");
  const detail = event.status ?? event.iteration ?? event.message ?? "";
  return `[${type}] ${String(detail)}`.trim();
}

export default function EngineeringBottomPanel(props: Props) {
  const {
    terminalSession, terminalStatus, terminalCommand, terminalOutput, events, run,
    browserUrl, browserOpen, matlabDiagnostic, runtimeDiagnostic,
    onTerminalCommandChange, onBrowserUrlChange, onStartTerminal, onStopTerminal,
    onSendTerminalCommand, onToggleBrowser, onNavigateBrowser,
  } = props;
  const [active, setActive] = useState<BottomTab>("terminal");
  const toolEvents = events.filter(event => /tool/i.test(String(event.type || event.kind || "")));

  return <section className="engineering-bottom-panel">
    <nav className="bottom-tabbar" role="tablist" aria-label="下栏面板">
      {tabs.map(tab => <button key={tab.id} role="tab" aria-selected={active === tab.id} className={active === tab.id ? "active" : ""} onClick={() => setActive(tab.id)}>{tab.label}</button>)}
    </nav>
    <div className="bottom-tab-content" role="tabpanel">
      {active === "terminal" ? <div className="terminal-panel">
        <div className="terminal-toolbar"><span><Terminal size={14}/>MATLAB 终端 <em>{terminalStatus}</em></span><input aria-label="MATLAB 命令" value={terminalCommand} onChange={event => onTerminalCommandChange(event.target.value)} onKeyDown={event => { if (event.key === "Enter") onSendTerminalCommand(); }} placeholder="输入 MATLAB 命令" disabled={!terminalSession}/><button onClick={onStartTerminal} disabled={Boolean(terminalSession)}><Terminal size={13}/>启动</button><button className="secondary" onClick={onStopTerminal} disabled={!terminalSession}><Square size={12}/>停止</button><button onClick={onSendTerminalCommand} disabled={!terminalSession || !terminalCommand.trim()}><Send size={13}/>发送</button></div>
        <pre className="bottom-console">{terminalOutput.join("\n") || "MATLAB 终端尚未启动。终端仅在用户明确点击“启动”后运行。"}</pre>
      </div> : null}
      {active === "log" ? <pre className="bottom-console">{events.map(eventLine).join("\n") || "尚无运行事件。"}</pre> : null}
      {active === "output" ? <pre className="bottom-console">{terminalOutput.join("\n") || (run ? JSON.stringify({ runId: run.runId, status: run.status, metrics: run.metrics }, null, 2) : "尚无工程输出。")}</pre> : null}
      {active === "tools" ? <pre className="bottom-console">{toolEvents.map(eventLine).join("\n") || "工程链路没有科研工具调用；Research 工具事件只在 AI 科研工作区显示。"}</pre> : null}
      {active === "artifacts" ? <div className="bottom-artifacts"><header><FileJson2 size={14}/><b>本次运行制品</b><span>{run ? run.files.length + run.snapshots.length : 0} 项</span></header>{run ? [...run.files, ...run.snapshots].map(item => <div key={item.sha256}><span>{item.relativePath}</span><small>{(item.sizeBytes / 1024).toFixed(1)} KB</small><code>{item.sha256.slice(0, 12)}</code></div>) : <p>尚未运行，不能生成或展示伪造制品。</p>}</div> : null}
      {active === "diagnostics" ? <div className="bottom-diagnostics"><div><b>MATLAB</b><span>{matlabDiagnostic}</span></div><div><b>Runtime</b><span>{runtimeDiagnostic}</span></div><div><b>当前运行</b><span>{run ? `${run.runId} · ${run.status}` : "无"}</span></div>{run?.error ? <div className="diagnostic-error"><b>{run.error.code}</b><span>{run.error.message}</span></div> : null}</div> : null}
      {active === "browser" ? <div className="browser-panel"><div className="browser-toolbar"><span><Globe2 size={14}/>受限浏览器</span><input aria-label="浏览器地址" value={browserUrl} onChange={event => onBrowserUrlChange(event.target.value)} onKeyDown={event => { if (event.key === "Enter") onNavigateBrowser(); }}/><button onClick={onNavigateBrowser}>{browserOpen ? "导航" : "打开"}</button><button className="secondary" onClick={onToggleBrowser}>{browserOpen ? "关闭" : "新建"}</button></div><div className="browser-empty"><Boxes size={22}/><b>{browserOpen ? "子 WebView 已打开" : "浏览器尚未打开"}</b><span>只允许后端白名单中的 http/https 地址；弹窗和任意下载不在此面板授权。</span></div></div> : null}
    </div>
  </section>;
}

export function EngineeringRunButton({ busy, label: _label, disabled = false, onRun }: { busy: boolean; label: string; disabled?: boolean; onRun: () => void }) {
  return <button className="run-button center-run-button" onClick={onRun} disabled={busy || disabled}><Play size={14}/>{busy ? "优化中" : "开始优化"}</button>;
}