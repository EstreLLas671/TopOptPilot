import { invoke } from "@tauri-apps/api/core";
import type { BackendInfo, Locale, MatlabHealth, Research } from "./types";

let backend: BackendInfo | null = null;

export async function initializeBackend(): Promise<BackendInfo> {
  if (backend) return backend;
  if (import.meta.env.VITE_API_URL) {
    backend = { port: Number(new URL(import.meta.env.VITE_API_URL).port), token: import.meta.env.VITE_API_TOKEN || "" };
    return backend;
  }
  // A cold PyInstaller one-file extraction can take >20 s while Defender scans it.
  for (let attempt = 0; attempt < 240; attempt++) {
    try {
      const value = await invoke<BackendInfo | null>("backend_info");
      if (value?.port) { backend = value; return value; }
    } catch { /* sidecar is still starting */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("Desktop backend did not become ready");
}

function base(): string { if (!backend) throw new Error("Backend not initialized"); return `http://127.0.0.1:${backend.port}`; }
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  await initializeBackend();
  let lastError: unknown;
  // The handshake can precede Uvicorn's accept loop by a fraction of a second,
  // and Defender may briefly hold the extracted executable on a cold start.
  for (let attempt = 0; attempt < 20; attempt++) {
    try {
      const response = await fetch(base() + path, { ...init, headers: { "Content-Type": "application/json",
        "X-TopOptPilot-Token": backend!.token, ...(init.headers || {}) } });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
      return response.json();
    } catch (reason) {
      lastError = reason;
      if (reason instanceof Error && !/Failed to fetch|NetworkError|Load failed/i.test(reason.message)) throw reason;
      await new Promise(resolve => setTimeout(resolve, Math.min(1000, 150 + attempt * 75)));
    }
  }
  throw lastError instanceof Error ? lastError : new Error("Desktop backend request failed");
}

export const api = {
  listResearch: () => request<Research[]>("/api/research"),
  getResearch: (id: string) => request<Research>(`/api/research/${id}`),
  createResearch: (data: object) => request<Research>("/api/research", { method: "POST", body: JSON.stringify(data) }),
  autonomous: (id: string) => request<Research>(`/api/research/${id}/autonomous`, { method: "POST" }),
  command: (id: string, text: string, selected_experiment?: string) => request<{ok:boolean;message:string;action:string;data:Record<string,unknown>}>(`/api/research/${id}/commands`, { method: "POST", body: JSON.stringify({ text, selected_experiment }) }),
  approve: (id: string) => request(`/api/decision/${id}/approve`, { method: "POST" }),
  reject: (id: string) => request(`/api/decision/${id}/reject`, { method: "POST" }),
  editDecision: (id: string, parameters: object) => request(`/api/decision/${id}/edit`, { method: "POST", body: JSON.stringify({ parameters }) }),
  why: (id: string) => request<{reason:string}>(`/api/decision/${id}/why`),
  setLocale: (id: string, locale: Locale) => request<Research>(`/api/research/${id}/locale`, { method: "PATCH", body: JSON.stringify({ locale }) }),
  matlabHealth: () => request<MatlabHealth>("/api/matlab/health"),
  restartMatlab: () => request<MatlabHealth>("/api/matlab/restart", { method: "POST" }),
  stream(id: string): WebSocket { if (!backend) throw new Error("Backend not initialized"); return new WebSocket(`ws://127.0.0.1:${backend.port}/api/research/${id}/stream?token=${encodeURIComponent(backend.token)}`); }
};
