import { useState } from "react";
import { Bot, LoaderCircle, Send, ShieldCheck } from "lucide-react";
import { api } from "../../api";
import type { EngineeringRun, ProjectFile } from "../../types";
import type { OptimizationConfig } from "../../optimization-config";

type Props = {
  projectId: string;
  selectedFile: ProjectFile | null;
  run: EngineeringRun | null;
  config: OptimizationConfig;
  onError: (message: string) => void;
};

type ChatMessage = { role: "user" | "assistant"; content: string; source?: string };

export default function EngineeringChatPanel({ projectId, selectedFile, run, config, onError }: Props) {
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [allowExternalSource, setAllowExternalSource] = useState(false);
  const [busy, setBusy] = useState(false);

  async function send() {
    const value = message.trim();
    if (!value || busy) return;
    setMessages(items => [...items, { role: "user", content: value }]);
    setMessage("");
    setBusy(true);
    try {
      const response = await api.engineeringChat({
        message: value,
        projectId: projectId || undefined,
        relativePath: selectedFile?.relative_path || undefined,
        context: {
          runId: run?.runId,
          parameters: config,
          selectedText: "",
          fileDigest: selectedFile?.sha256,
          ...(allowExternalSource && selectedFile ? { source: selectedFile.content } : {}),
        },
        allowExternalSource,
      });
      setMessages(items => [...items, { role: "assistant", content: response.reply, source: response.source }]);
    } catch (reason) {
      onError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <section className="engineering-chat-panel" aria-label="工程开发聊天">
    <header className="chat-panel-header"><div><span className="eyebrow">ENGINEERING ASSISTANT</span><h2>工程开发聊天</h2><p>询问求解链路、参数和结果；代码修改仍需进入补丁审批。</p></div><span className="chat-boundary"><ShieldCheck size={13}/>只读对话</span></header>
    <div className="chat-message-list">
      {!messages.length ? <div className="chat-empty"><Bot size={30}/><b>从当前工程上下文开始</b><span>可以询问 MATLAB、参数配置、运行结果或下一步工程操作。</span></div> : messages.map((item, index) => <article className={`chat-message ${item.role}`} key={`${item.role}-${index}`}><span className="chat-avatar">{item.role === "assistant" ? <Bot size={14}/> : "你"}</span><div><p>{item.content}</p>{item.source ? <small>{item.source === "not_configured" ? "未配置 Qwen，当前为 Safe Mode" : item.source}</small> : null}</div></article>)}
    </div>
    <footer className="chat-composer"><label><input type="checkbox" checked={allowExternalSource} onChange={event => setAllowExternalSource(event.target.checked)}/>允许本次把当前文件源代码发送给 Qwen</label><div><textarea value={message} onChange={event => setMessage(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="询问当前工程、参数或结果…" /><button aria-label="发送聊天消息" onClick={() => void send()} disabled={!message.trim() || busy}>{busy ? <LoaderCircle className="spin" size={15}/> : <Send size={15}/>}</button></div></footer>
  </section>;
}
