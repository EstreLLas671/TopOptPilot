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
  conversationHistory?: Conversation[];
  onHistoryChange?: (items: Conversation[], currentId: string) => void;
  onApplySuggestedConfig?: (action: OptimizationConfigAction) => void;
};

type PendingAttachment = ConversationAttachment & { preview: string };

const configLabels: Record<string, string> = {
  dimension: "维度", bcType: "工况", accuracy: "精度", nelx: "X 向网格", nely: "Y 向网格", nelz: "Z 向网格",
  volfrac: "体积分数", penal: "惩罚因子", rmin: "滤波半径", maxIterations: "最大迭代",
  minIterations: "最小迭代", filterStrategy: "滤波策略", material: "材料",
};
const EMPTY_CONVERSATIONS: Conversation[] = [];

function sameConversationList(left: Conversation[], right: Conversation[]): boolean {
  return left.length === right.length && left.every((item, index) => {
    const other = right[index];
    return Boolean(other)
      && item.id === other.id
      && item.title === other.title
      && item.updatedAt === other.updatedAt;
  });
}

function displayConfigValue(value: unknown): string {
  if (value && typeof value === "object") {
    const material = value as Record<string, unknown>;
    return [material.name, material.youngsModulusGPa ? `E ${material.youngsModulusGPa} GPa` : null].filter(Boolean).join(" · ");
  }
  return String(value ?? "—");
}
type EngineeringChatDraft = { message: string; allowExternalSource: boolean; attachments: PendingAttachment[] };
const engineeringChatDrafts = new Map<string, EngineeringChatDraft>();

export default function EngineeringChatPanel({ projectId, selectedFile, run, config, onError, requestedConversationId = "", conversationHistory: externalConversations = EMPTY_CONVERSATIONS, onHistoryChange, onApplySuggestedConfig }: Props) {
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
  const messageList = useRef<HTMLDivElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const followMessages = useRef(true);
  const uploadingHashes = useRef(new Set<string>());
  const conversationLoadGeneration = useRef(0);
  const activeConversationRef = useRef("");
  const draftKey = `topoptpilot:engineering-draft:${ownerId}:${conversationId || "new"}`;
  const draftRef = useRef<EngineeringChatDraft>({ message: "", allowExternalSource: false, attachments: [] });
  const hydratedDraftKey = useRef("");
  draftRef.current = { message, allowExternalSource, attachments };
  useEffect(() => {
    if (!draftKey || hydratedDraftKey.current === draftKey) return;
    const memory = engineeringChatDrafts.get(draftKey);
    if (memory) {
      setMessage(memory.message);
      setAllowExternalSource(memory.allowExternalSource);
      setAttachments(memory.attachments);
    } else {
      try {
        const saved = JSON.parse(localStorage.getItem(draftKey) || "null") as { message?: string; allowExternalSource?: boolean; attachments?: Array<ConversationAttachment & { preview?: string }> } | null;
        setMessage(saved?.message || "");
        setAllowExternalSource(Boolean(saved?.allowExternalSource));
        setAttachments(Array.isArray(saved?.attachments) ? saved.attachments.filter(item => item && typeof item.id === "string").map(item => ({ ...item, preview: typeof item.preview === "string" && item.preview.length < 350000 ? item.preview : "" })) : []);
      } catch {
        setMessage(""); setAllowExternalSource(false); setAttachments([]);
      }
    }
    hydratedDraftKey.current = draftKey;
    return () => {
      const draft = draftRef.current;
      engineeringChatDrafts.set(draftKey, { ...draft, attachments: [...draft.attachments] });
      localStorage.setItem(draftKey, JSON.stringify({ message: draft.message, allowExternalSource: draft.allowExternalSource, attachments: draft.attachments.map(({ preview, ...item }) => ({ ...item, ...(preview && preview.length < 350000 ? { preview } : {}) })) }));
    };
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey || hydratedDraftKey.current !== draftKey) return;
    const draft = draftRef.current;
    engineeringChatDrafts.set(draftKey, { ...draft, attachments: [...draft.attachments] });
    localStorage.setItem(draftKey, JSON.stringify({
      message: draft.message,
      allowExternalSource: draft.allowExternalSource,
      attachments: draft.attachments.map(({ preview, ...item }) => ({ ...item, ...(preview && preview.length < 350000 ? { preview } : {}) })),
    }));
  }, [draftKey, message, allowExternalSource, attachments]);

  async function loadConversation(id: string, preserveDraft = false) {
    const generation = ++conversationLoadGeneration.current;
    activeConversationRef.current = id;
    setConversationId(id);
    const loaded = await api.conversationMessages(id);
    if (generation !== conversationLoadGeneration.current || activeConversationRef.current !== id) return;
    setMessages(loaded);
    if (!preserveDraft) setAttachments([]);
    followMessages.current = true;
    window.requestAnimationFrame(() => messageEnd.current?.scrollIntoView?.({ block: "end" }));
  }

  async function createConversation() {
    const created = await api.conversationCreate("engineering", ownerId, "工程对话");
    setConversations(items => [created, ...items]);
    hydratedDraftKey.current = `topoptpilot:engineering-draft:${ownerId}:${created.id}`;
    await loadConversation(created.id, true);
    return created.id;
  }

  useEffect(() => {
    const generation = ++conversationLoadGeneration.current;
    activeConversationRef.current = "";
    let cancelled = false;
    void api.conversationList("engineering", ownerId).then(async items => {
      if (cancelled || generation !== conversationLoadGeneration.current) return;
      setConversations(items);
      const id = items[0]?.id;
      if (!cancelled && id) await loadConversation(id);
      else if (!cancelled) { setConversationId(""); setMessages([]); }
    }).catch(reason => { if (!cancelled) onError(String(reason)); });
    return () => { cancelled = true; };
  }, [ownerId]);
  useEffect(() => {
    setConversations(current => sameConversationList(current, externalConversations) ? current : externalConversations);
    if (conversationId && !externalConversations.some(item => item.id === conversationId)) {
      const next = externalConversations[0]?.id || "";
      if (next) void loadConversation(next);
      else {
        conversationLoadGeneration.current += 1;
        activeConversationRef.current = "";
        setConversationId("");
        setMessages([]);
      }
    }
  }, [externalConversations]);
  useEffect(() => {
    if (!sameConversationList(conversations, externalConversations)) {
      onHistoryChange?.(conversations, conversationId);
      return;
    }
    onHistoryChange?.(externalConversations, conversationId);
  }, [conversationId, conversations, externalConversations, onHistoryChange]);

  useEffect(() => {
    if (!requestedConversationId || requestedConversationId === conversationId) return;
    void loadConversation(requestedConversationId).catch(reason => onError(String(reason)));
  }, [requestedConversationId, ownerId, conversationId]);

  useEffect(() => {
    if (!followMessages.current) return;
    window.requestAnimationFrame(() => messageEnd.current?.scrollIntoView?.({ block: "end" }));
  }, [messages, busy]);

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
    if ((!value && !attachments.length) || busy) return;
    let targetConversationId = conversationId;
    if (!targetConversationId) targetConversationId = await createConversation();
    const attachmentIds = attachments.map(item => item.id);
    setMessage("");
    setAttachments([]);
    setBusy(true);
    try {
      const user = await api.conversationMessage(targetConversationId, {
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
      const assistant = await api.conversationMessage(targetConversationId, {
        role: "assistant", content: response.reply, source: response.source,
      });
      setMessages(items => [...items, assistant]);
      setMessage("");
      setAttachments([]);
      setSuggestedAction(response.actions.map(parseOptimizationConfigAction).find(Boolean) || null);
      const updatedAt = Date.now();
      setConversations(items => items
        .map(item => item.id === targetConversationId ? { ...item, updatedAt } : item)
        .sort((a, b) => b.updatedAt - a.updatedAt));
    } catch (reason) {
      onError(String(reason));
    } finally {
      setBusy(false);
    }
  }

  return <section ref={dropZone} className={"engineering-chat-panel chat-drop-zone" + (dragActive ? " drag-active" : "")} aria-label="工程开发聊天" {...dropHandlers}>
    {dragActive ? <div className="chat-drop-overlay"><ImagePlus size={20}/><b>松开以上传附件</b><span>图片、PDF、Word、Excel、SVG、文本 · 单个不超过 10 MB</span></div> : null}
    <header className="chat-panel-header">
      <div><span className="eyebrow">ENGINEERING ASSISTANT</span><h2>工程开发聊天</h2></div>
    </header>
    <div ref={messageList} className="chat-message-list" onScroll={() => {
      const node = messageList.current;
      if (node) followMessages.current = node.scrollHeight - node.scrollTop - node.clientHeight < 80;
    }}>
      {!messages.length ? <div className="chat-empty"><Bot size={30}/><b>从当前工程上下文开始</b><span>询问 MATLAB、参数或结果，也可上传图片和常用文档。</span></div> : messages.map(item => <article className={"chat-message " + item.role} key={item.id}><span className="chat-avatar">{item.role === "assistant" ? <Bot size={14}/> : "你"}</span><div><p>{item.content}</p>{item.attachments?.length ? <small>{item.attachments.length} 个附件 · 已随会话保存在本地</small> : null}{item.source ? <small>{item.source === "not_configured" ? "未配置 Qwen" : item.source}</small> : null}</div></article>)}
      {suggestedAction ? <div className="suggestion-dialog-backdrop" role="presentation"><section className="optimization-action-card suggestion-dialog" role="dialog" aria-modal="true" aria-label="应用建议参数"><header><b>Agent 建议参数</b><button className="dialog-icon-button" aria-label="取消建议参数" title="取消" onClick={() => setSuggestedAction(null)}><X size={14}/></button></header><p>{suggestedAction.rationale || "AI 返回了一组完整且通过校验的优化配置。"}</p><div className="optimization-action-diff">{suggestedAction.changedFields.map(field => <div key={field}><b>{configLabels[field] || field}</b><span>{displayConfigValue(config[field as keyof OptimizationConfig])}</span><i>→</i><strong>{displayConfigValue(suggestedAction.config[field as keyof OptimizationConfig])}</strong></div>)}</div><footer><button className="outline-button" onClick={() => setSuggestedAction(null)}>取消</button><button className="primary-button" onClick={() => { onApplySuggestedConfig?.(suggestedAction); setSuggestedAction(null); }}>填入参数</button></footer></section></div> : null}
      <div ref={messageEnd} className="chat-message-end" aria-hidden="true"/>
    </div>
    <footer className="chat-composer">
      {attachments.length ? <div className="chat-attachment-preview">{attachments.map(item => <figure key={item.id}>{item.preview ? <img src={item.preview} alt={item.fileName || "待发送附件"}/> : <span className="attachment-file-name">{item.fileName || "附件"}</span>}<button aria-label="移除附件" onClick={() => setAttachments(values => values.filter(value => value.id !== item.id))}><X size={12}/></button></figure>)}</div> : null}
      <label><input type="checkbox" checked={allowExternalSource} onChange={event => setAllowExternalSource(event.target.checked)}/>允许本次把当前文件源代码发送给 Qwen</label>
      <div>
        <input ref={fileInput} hidden type="file" accept="image/png,image/jpeg,image/webp,image/svg+xml,application/pdf,.docx,.xlsx,.txt,.md,.csv" multiple onChange={event => void uploadFiles(event.target.files)}/>
        <button type="button" className="chat-composer-action" aria-label="上传附件" title="上传附件" onClick={() => fileInput.current?.click()} disabled={busy}><ImagePlus size={15}/></button>
        <textarea value={message} onChange={event => setMessage(event.target.value)} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void send(); } }} placeholder="询问当前工程、参数或结果…" />
        <button className="chat-composer-action" aria-label="发送聊天消息" title="发送" onClick={() => void send()} disabled={(!message.trim() && !attachments.length) || busy}>{busy ? <LoaderCircle className="spin" size={15}/> : <Send size={15}/>}</button>
      </div>
    </footer>
  </section>;
}
