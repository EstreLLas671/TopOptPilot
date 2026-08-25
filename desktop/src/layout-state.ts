import type { WorkspaceMode } from "./workspace";

export type PanelName = "left" | "right" | "bottom";

export interface WorkspaceLayout {
  leftOpen: boolean;
  rightOpen: boolean;
  bottomOpen: boolean;
  leftWidth: number;
  rightWidth: number;
  bottomHeight: number;
}

export const DEFAULT_LAYOUT: WorkspaceLayout = Object.freeze({
  leftOpen: true,
  rightOpen: true,
  bottomOpen: false,
  leftWidth: 280,
  rightWidth: 380,
  bottomHeight: 300,
});

export const LAYOUT_LIMITS = Object.freeze({
  leftWidth: { min: 240, max: 420 },
  rightWidth: { min: 320, max: 520 },
  bottomHeight: { min: 180, max: 520 },
});

export const LAYOUT_STORAGE_KEYS: Record<WorkspaceMode, string> = Object.freeze({
  engineering: "idesktop-v2.layout.engineering.v3",
  research: "idesktop-v2.layout.research.v3",
});

function numberOr(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function boolOr(value: unknown, fallback: boolean) {
  return typeof value === "boolean" ? value : fallback;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** Clamp persisted or pointer-derived dimensions while preserving visibility. */
export function clampLayout(input: Partial<WorkspaceLayout>, _viewport?: { viewportWidth?: number }): WorkspaceLayout {
  return {
    leftOpen: boolOr(input.leftOpen, DEFAULT_LAYOUT.leftOpen),
    rightOpen: boolOr(input.rightOpen, DEFAULT_LAYOUT.rightOpen),
    bottomOpen: boolOr(input.bottomOpen, DEFAULT_LAYOUT.bottomOpen),
    leftWidth: clamp(numberOr(input.leftWidth, DEFAULT_LAYOUT.leftWidth), LAYOUT_LIMITS.leftWidth.min, LAYOUT_LIMITS.leftWidth.max),
    rightWidth: clamp(numberOr(input.rightWidth, DEFAULT_LAYOUT.rightWidth), LAYOUT_LIMITS.rightWidth.min, LAYOUT_LIMITS.rightWidth.max),
    bottomHeight: clamp(numberOr(input.bottomHeight, DEFAULT_LAYOUT.bottomHeight), LAYOUT_LIMITS.bottomHeight.min, LAYOUT_LIMITS.bottomHeight.max),
  };
}

export function togglePanel(layout: WorkspaceLayout, panel: PanelName): WorkspaceLayout {
  if (panel === "left") return { ...layout, leftOpen: !layout.leftOpen };
  if (panel === "right") return { ...layout, rightOpen: !layout.rightOpen };
  return { ...layout, bottomOpen: !layout.bottomOpen };
}

function defaultStorage(): Storage | null {
  return typeof window === "undefined" ? null : window.localStorage;
}

export function loadWorkspaceLayout(mode: WorkspaceMode, storage: Storage | null = defaultStorage()): WorkspaceLayout {
  if (!storage) return { ...DEFAULT_LAYOUT };
  try {
    const raw = storage.getItem(LAYOUT_STORAGE_KEYS[mode]);
    if (!raw) return { ...DEFAULT_LAYOUT };
    return clampLayout(JSON.parse(raw) as Partial<WorkspaceLayout>);
  } catch {
    return { ...DEFAULT_LAYOUT };
  }
}

export function saveWorkspaceLayout(mode: WorkspaceMode, layout: WorkspaceLayout, storage: Storage | null = defaultStorage()): WorkspaceLayout {
  const normalized = clampLayout(layout);
  if (storage) {
    try { storage.setItem(LAYOUT_STORAGE_KEYS[mode], JSON.stringify(normalized)); } catch { /* quota/private mode: in-memory state still works */ }
  }
  return normalized;
}

export function resetWorkspaceLayout(mode: WorkspaceMode, storage: Storage | null = defaultStorage()): WorkspaceLayout {
  const reset = { ...DEFAULT_LAYOUT };
  if (storage) {
    try { storage.setItem(LAYOUT_STORAGE_KEYS[mode], JSON.stringify(reset)); } catch { /* best effort */ }
  }
  return reset;
}
