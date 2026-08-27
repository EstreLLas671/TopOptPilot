import { type DragEvent, type RefObject, useEffect, useRef, useState } from "react";
import { api } from "./api";

export const CHAT_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "image/svg+xml", "text/plain", "text/csv"] as const;
export const CHAT_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
export const CHAT_IMAGE_MAX_COUNT = 4;

export type ChatImageMediaType = typeof CHAT_IMAGE_TYPES[number];
export type DroppedImageCandidate = {
  fileName: string;
  mediaType: ChatImageMediaType;
  sizeBytes: number;
  dataBase64: string;
  preview: string;
  sha256: string;
};

function mediaTypeFromBytes(bytes: Uint8Array, fileName: string): ChatImageMediaType | null {
  if (bytes.length >= 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47
    && bytes[4] === 0x0d && bytes[5] === 0x0a && bytes[6] === 0x1a && bytes[7] === 0x0a) return "image/png";
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (bytes.length >= 12 && String.fromCharCode(...bytes.slice(0, 4)) === "RIFF"
    && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP") return "image/webp";
  const extensionType = extensionMediaType(fileName);
  if (extensionType === "application/pdf" && bytes.length >= 5
    && String.fromCharCode(...bytes.slice(0, 5)) === "%PDF-") return extensionType;
  if ((extensionType === "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      || extensionType === "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    && bytes.length >= 4 && bytes[0] === 0x50 && bytes[1] === 0x4b
    && (bytes[2] === 0x03 || bytes[2] === 0x05 || bytes[2] === 0x07)
    && (bytes[3] === 0x04 || bytes[3] === 0x06 || bytes[3] === 0x08)) return extensionType;
  const head = new TextDecoder("utf-8", { fatal: false }).decode(bytes.slice(0, 4096)).replace(/^\uFEFF/, "").trimStart().toLowerCase();
  if (extensionType === "image/svg+xml" && head.includes("<svg")) return extensionType;
  if ((extensionType === "text/plain" || extensionType === "text/csv")
    && !bytes.slice(0, 4096).some(value => value === 0)) return extensionType;
  return null;
}

function extensionMediaType(fileName: string): ChatImageMediaType | null {
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".pdf")) return "application/pdf";
  if (lower.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (lower.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  if (lower.endsWith(".svg")) return "image/svg+xml";
  if (lower.endsWith(".txt") || lower.endsWith(".md")) return "text/plain";
  if (lower.endsWith(".csv")) return "text/csv";
  return null;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return btoa(binary);
}

async function digestSha256(bytes: Uint8Array): Promise<string> {
  const input = new Uint8Array(bytes.byteLength);
  input.set(bytes);
  const digest = await crypto.subtle.digest("SHA-256", input.buffer);
  return Array.from(new Uint8Array(digest), value => value.toString(16).padStart(2, "0")).join("");
}

export async function imageCandidateFromFile(file: File): Promise<DroppedImageCandidate> {
  if (file.size > CHAT_IMAGE_MAX_BYTES) throw new Error("单个附件不能超过 10 MB。");
  const bytes = new Uint8Array(await file.arrayBuffer());
  const mediaType = mediaTypeFromBytes(bytes, file.name);
  if (!mediaType) throw new Error("附件格式不受支持，或文件内容与扩展名不一致。");
  const extensionType = extensionMediaType(file.name);
  if (extensionType && extensionType !== mediaType) throw new Error(`附件扩展名与实际格式不一致：${file.name}`);
  if (file.type && file.type !== "application/octet-stream"
    && CHAT_IMAGE_TYPES.includes(file.type as ChatImageMediaType) && file.type !== mediaType) {
    throw new Error(`附件声明格式与实际格式不一致：${file.name}`);
  }
  const dataBase64 = bytesToBase64(bytes);
  return {
    fileName: file.name || "dropped-attachment",
    mediaType,
    sizeBytes: bytes.length,
    dataBase64,
    preview: ["image/png", "image/jpeg", "image/webp"].includes(mediaType) ? `data:${mediaType};base64,${dataBase64}` : "",
    sha256: await digestSha256(bytes),
  };
}

export async function imageCandidatesFromDataTransfer(dataTransfer: DataTransfer): Promise<DroppedImageCandidate[]> {
  const files: File[] = [];
  const seen = new Set<string>();
  for (const item of Array.from(dataTransfer.items || [])) {
    if (item.kind !== "file") continue;
    const file = item.getAsFile();
    if (!file) continue;
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
    if (!seen.has(key)) { seen.add(key); files.push(file); }
  }
  for (const file of Array.from(dataTransfer.files || [])) {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
    if (!seen.has(key)) { seen.add(key); files.push(file); }
  }
  if (!files.length) throw new Error("外部应用未提供可读取的文件，请先保存后再拖入。");
  return Promise.all(files.map(imageCandidateFromFile));
}

type NativeDragPayload = {
  type: "enter" | "over" | "drop" | "leave";
  paths?: string[];
  position?: { x: number; y: number };
};

function pointInside(element: HTMLElement | null, position?: { x: number; y: number }): boolean {
  if (!element || !position) return true;
  const scale = window.devicePixelRatio || 1;
  const point = { x: position.x / scale, y: position.y / scale };
  const rect = element.getBoundingClientRect();
  return point.x >= rect.left && point.x <= rect.right && point.y >= rect.top && point.y <= rect.bottom;
}

type UseImageDropOptions = {
  zoneRef: RefObject<HTMLElement | null>;
  disabled?: boolean;
  onCandidates: (candidates: DroppedImageCandidate[]) => void | Promise<void>;
  onError: (message: string) => void;
};

export function useChatImageDrop({ zoneRef, disabled = false, onCandidates, onError }: UseImageDropOptions) {
  const [dragActive, setDragActive] = useState(false);
  const depth = useRef(0);
  const onCandidatesRef = useRef(onCandidates);
  const onErrorRef = useRef(onError);
  useEffect(() => { onCandidatesRef.current = onCandidates; }, [onCandidates]);
  useEffect(() => { onErrorRef.current = onError; }, [onError]);

  useEffect(() => {
    if (disabled || !("__TAURI_INTERNALS__" in window)) return;
    let disposed = false;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/webview").then(({ getCurrentWebview }) => getCurrentWebview().onDragDropEvent(async event => {
      if (disposed) return;
      const payload = event.payload as NativeDragPayload;
      const inside = pointInside(zoneRef.current, payload.position);
      if (payload.type === "leave") { depth.current = 0; setDragActive(false); return; }
      if (!inside) return;
      if (payload.type === "enter" || payload.type === "over") { setDragActive(true); return; }
      if (payload.type !== "drop") return;
      depth.current = 0;
      setDragActive(false);
      if (!payload.paths?.length) {
        onErrorRef.current("外部应用未提供可读取的文件路径，请先保存后再拖入。");
        return;
      }
      try {
        const values = await api.readDroppedImages(payload.paths);
        await onCandidatesRef.current(values.map(value => ({
          ...value,
          mediaType: value.mediaType as ChatImageMediaType,
          preview: ["image/png", "image/jpeg", "image/webp"].includes(value.mediaType)
            ? `data:${value.mediaType};base64,${value.dataBase64}` : "",
        })));
      } catch (reason) { onErrorRef.current(String(reason)); }
    })).then(value => { if (disposed) value(); else unlisten = value; }).catch(() => undefined);
    return () => { disposed = true; unlisten?.(); setDragActive(false); };
  }, [disabled, zoneRef]);

  const handlers = {
    onDragEnter(event: DragEvent<HTMLElement>) {
      if (disabled || !Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      depth.current += 1;
      setDragActive(true);
    },
    onDragOver(event: DragEvent<HTMLElement>) {
      if (disabled || !Array.from(event.dataTransfer.types).includes("Files")) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    onDragLeave(event: DragEvent<HTMLElement>) {
      event.preventDefault();
      depth.current = Math.max(0, depth.current - 1);
      if (!depth.current) setDragActive(false);
    },
    async onDrop(event: DragEvent<HTMLElement>) {
      event.preventDefault();
      depth.current = 0;
      setDragActive(false);
      if (disabled) return;
      try { await onCandidates(await imageCandidatesFromDataTransfer(event.dataTransfer)); }
      catch (reason) { onError(String(reason)); }
    },
  };
  return { dragActive, handlers };
}
