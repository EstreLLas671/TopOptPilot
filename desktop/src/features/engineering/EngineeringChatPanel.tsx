import { useEffect, useRef, useState } from "react";
import { Bot, ImagePlus, LoaderCircle, Send, X } from "lucide-react";
import { api } from "../../api";
import type { Conversation, ConversationAttachment, ConversationMessage, EngineeringRun, ProjectFile } from "../../types";
import { parseOptimizationConfigAction, type OptimizationConfig, type OptimizationConfigAction } from "../../optimization-config";
import { CHAT_IMAGE_MAX_COUNT, imageCandidateFromFile, useChatImageDrop, type DroppedImageCandidate } from "../../chat-image-drop";

type Props = {
  projectId: string;
  selectedFile: ProjectFile | null;
  run: EngineeringRun | null;
  config: OptimizationConfig;
  onError: (message: string) => void;
  requestedConversationId?: string;
  onHistoryChange?: (items: Conversation[], currentId: string) => void;
  onApplySuggestedConfig?: (action: OptimizationConfigAction) => void;
};

type PendingAttachment = ConversationAttachment & { preview: string };
type EngineeringChatDraft = { message: string; allowExternalSource: boolean; attachments: PendingAttachment[] };
const engineeringChatDrafts = new Map<string, EngineeringChatDraft>();

export default function EngineeringChatPanel({ projectId, selectedFile, run, config, onError, requestedConversationId = "", onHistoryChange, onApplySuggestedConfig }: Props) {
  const ownerId = projectId || "engineering-unbound";
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [allowExternalSource, setAllowExternalSource] = useState(false);
  const [busy, setBusy] = useState(false);
  const [suggestedAction, setSuggestedAction] = useState<OptimizationConfigAction | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const dropZone = useRef<HTMLElement>(null);
  const uploadingHashes = useRef(new Set<string>());
  const draftKey = conversationId ? `topoptpilot:engineering-draft:${ownerId}:${conversationId}` : "";
  const draftRef = useRef<EngineeringChatDraft>({ message: "", allowExternalSource: false, attachments: [] });
  draftRef.current = { message, allowExternalSource, attachments };
  useEffect(() => {
    if (!draftKey) return;
    const memory = engineeringChatDrafts.get(draftKey);
    if (memory) {
      setMessage(memory.message);
      setAllowExternalSource(memory.allowExternalSource);
      setAttachments(memory.attachments);
    } else {
      try {
        const saved = JSON.parse(localStorage.getItem(draftKey) || "null") as { message?: string; allowExternalSource?: boolean } | null;
        setMessage(saved?.message || "");
        setAllowExternalSource(Boolean(saved?.allowExternalSource));
        setAttachments([]);
      } catch {
        setMessage(""); setAllowExternalSource(false); setAttachments([]);
      }
    }
    return () => {
      const draft = draftRef.current;
      engineeringChatDrafts.set(draftKey, { ...draft, attachments: [...draft.attachments] });
      localStorage.setItem(draftKey, JSON.stringify({ message: draft.message, allowExternalSource: draft.allowExternalSource }));
    };
  }, [draftKey]);

  async function loadConversation(id: string) {
    setConversationId(id);
    setMessages(await api.conversationMessages(id));
    setAttachments([]);
  }

  async function createConversation() {
    const created = await api.conversationCreate("engineering", ownerId, "工程对话");
    setConversations(items => [created, ...items]);
    await loadConversation(created.id);
    return created.id;
  }

  useEffect(() => {
    let cancelled = false;
    void api.conversationList("engineering", ownerId).then(async items => {
      if (cancelled) return;
      setConversations(items);
      const id = items[0]?.id || await createConversation();
      if (!cancelled) await loadConversation(id);
    }).catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [ownerId]);
  useEffect(() => {
    onHistoryChange?.(conversations, conversationId);
  }, [conversationId, conversations, onHistoryChange]);

  useEffect(() => {
    if (!requestedConversationId || requestedConversationId === conversationId) return;
    let cancelled = false;
    void api.conversationList("engineering", ownerId).then(async items => {
      if (cancelled) return;
      setConversations(items);
      if (items.some(item => item.id === requestedConversationId)) {
        await loadConversation(requestedConversationId);
      }
    }).catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [requestedConversationId, ownerId]);

  async function uploadCandidates(candidates: DroppedImageCandidate[]) {
    const existing = new Set(attachments.flatMap(item => item.sha256 ? [item.sha256] : []));
    const unique = candidates.filter(candidate => {
      if (existing.has(candidate.sha256) || uploadingHashes.current.has(candidate.sha256)) return false;
      existing.add(candidate.sha256);
      uploadingHashes.current.add(candidate.sha256);
      return true;
    });
    if (!unique.length) return;
    if (attachments.length + unique.length > CHAT_IMAGE_MAX_COUNT) {
      unique.forEach(item => uploadingHashes.current.delete(item.sha256));
      return onError("每条消息最多上传 4 个附件。");
    }
    let id = conversationId;
    if (!id) id = await createConversation();
    setBusy(true);
    try {
      const next: PendingAttachment[] = [];
      for (const candidate of unique) {
        const uploaded = await api.conversationAttachment(id, {
          fileName: candidate.fileName, mediaType: candidate.mediaType, dataBase64: candidate.dataBase64,
        });
        next.push({ ...uploaded, fileName: candidate.fileName, sha256: uploaded.sha256 || candidate.sha256, preview: candidate.preview });
      }
      setAttachments(current => {
        const hashes = new Set(current.flatMap(item => item.sha256 ? [item.sha256] : []));
        return [...current, ...next.filter(item => !item.sha256 || !hashes.has(item.sha256))];
      });
    } catch (reason) {
      onError(String(reason));
    } finally {
      unique.forEach(item => uploadingHashes.current.delete(item.sha256));
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function uploadFiles(files: FileList | null) {
    if (!files?.length) return;
    try { await uploadCandidates(await Promise.all(Array.from(files).map(imageCandidateFromFile))); }
    catch (reason) { onError(String(reason)); }
  }
  const { dragActive, handlers: dropHandlers } = useChatImageDrop({
    zoneRef: dropZone,
    disabled: busy,
    onCandidates: uploadCandidates,
    onError,
  });
  async function send() {
    const value = message.trim();
    if ((!value && !attachments.length) || busy || !conversationId) return;
    const attachmentIds = attachments.map(item => item.id);
    setMessage("");
    setAttachments([]);
    setBusy(true);
    try {
      const user = await api.conversationMessage(conversationId, {
        role: "user", content: value || "请分析这些附件", attachmentIds,
      });
      setMessages(items => [...items, user]);
      const response = await api.engineeringChat({
        message: value || "请分析这些附件",
        projectId: projectId || undefined,
        relativePath: selectedFile?.relative_path || undefined,
        context: {
          runId: run?.runId, parameters: config, selectedText: "",
          fileDigest: selectedFile?.sha256,
          ...(allowExternalSource && selectedFile ? { source: selectedFile.content } : {}),
        },
        allowExternalSource,
        attachmentIds,
      });
      const assistant = await api.conversationMessage(conversationId, {
        role: "assistant", content: response.reply, source: response.source,
      });
      setMessages(items => [...items, assistant]);
            setMessage("");
      setAttachments([]);
      setSuggestedAction(response.actions.map(parseOptimizationConfigAction).find(Boolean) || null);
      setConversations(await api.conversationList("engineering", ownerId));
    } catch (reason) {
      onError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <section className="engineering-chat-panel" aria-label="工程开发聊天">
    <header className="chat-panel-header">
      <div><span className="eyebrow">ENGINEERING ASSISTANT</span><h2>工程开发聊天</h2></div>
    </header>
    <div className="chat-message-list">
      {!messages.length ? <div className="chat-empty"><Bot size={30}/><b>从当前工程上下文开始</b><span>询问 MATLAB、参数或结果，也可上传图片和常用文档。</span></div> : messages.map(item => <article className={"chat-message " + item.role} key={item.id}><span className="chat-avatar">{item.role === "assistant" ? <Bot size={14}/> : "你"}</span><div><p>{item.content}</p>{item.attachments?.length ? <small>{item.attachments.length} 个附件 · 已随会话保存在本地</small> : null}{item.source ? <small>{item.source === "not_configured" ? "未配置 Qwen" : item.source}</small> : null}</div></article>)}
      {suggestedAction ? <section className="optimization-action-card" aria-label="应用建议参数"><header><b>建议参数</b><span>仅填入配置，不会自动运行</span></header><p>{suggestedAction.rationale || "AI 返回了一组完整且通过校验的优化配置。"}</p><div className="optimization-action-fields">{suggestedAction.changedFields.map(field => <code key={field}>{field}</code>)}</div><details><summary>查看配置摘要</summary><pre>{JSON.stringify(suggestedAction.config, null, 2)}</pre></details><button className="primary-button" onClick={() => { onApplySuggestedConfig?.(suggestedAction); setSuggestedAction(null); }}>填入参数</button></section> : null}
    </div>
    <footer ref={dropZone} className={"chat-composer chat-drop-zone" + (dragActive ? " drag-active" : "")} {...dropHandlers}>
      {dragActive ? <div className="chat-drop-overlay"><ImagePlus size={20}/><b>松开以上传附件</b><span>图片、PDF、Word、Excel、SVG、文本 · 单个不超过 10 MB</span></div> : null}
      {attachments.length ? <div className="chat-attachment-preview">{attachments.map(item => <figure key={item.id}>{item.preview ? <img src={item.preview} alt={item.fileName || "待发送附件"}/> : <span className="attachment-file-name">{item.fileName || "附件"}</span>}<button aria-label="移除附件" onClick={() => setAttachments(values => values.filter(value => value.id !== item.id))}><X size={12}/></button></figure>)}</div> : null}
      <label><input type="checkbox" checked={allowExternalSource} onChange={event => setAllowExternalSource(event.target.checked)}/>允许本次把当前文件源代码发送给 Qwen</label>
      <div>
        <input ref={fileInput} hidden type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf,.docx,.xlsx,.txt,.md,.csv" multiple onChange={event => void uploadFiles(event.target.files)}/>
        <button type="button" aria-label="上传附件" onClick={() => fileInput.current?.click()} disabled={busy}><ImagePlus size={15}/></button>
        <textarea value={message} onChange={event => setMessage(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="询问当前工程、参数或结果…" />
        <button aria-label="发送聊天消息" onClick={() => void send()} disabled={(!message.trim() && !attachments.length) || busy}>{busy ? <LoaderCircle className="spin" size={15}/> : <Send size={15}/>}</button>
      </div>
    </footer>
  </section>;
}
