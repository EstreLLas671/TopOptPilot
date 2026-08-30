import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  LAYOUT_STORAGE_KEYS,
  LEGACY_ENGINEERING_LAYOUT_KEY,
  clampLayout,
  loadWorkspaceLayout,
  resetWorkspaceLayout,
  saveWorkspaceLayout,
  togglePanel,
  type WorkspaceLayout,
} from "./layout-state";

describe("workspace layout state", () => {
  it("uses the compact TopOptPilot defaults", () => {
    expect(DEFAULT_LAYOUT).toEqual({
      leftOpen: true,
      rightOpen: true,
      bottomOpen: false,
      leftWidth: 280,
      rightWidth: 380,
      bottomHeight: 300,
    });
  });

  it("clamps panel dimensions to safe minimum and maximum bounds", () => {
    expect(clampLayout({ ...DEFAULT_LAYOUT, leftWidth: 1, rightWidth: 9999, bottomHeight: -5 })).toMatchObject({
      leftWidth: 240,
      rightWidth: 520,
      bottomHeight: 180,
    });
  });

  it("keeps panel visibility independent and restores it without changing dimensions", () => {
    const hidden = togglePanel(DEFAULT_LAYOUT, "left");
    expect(hidden.leftOpen).toBe(false);
    expect(hidden.rightOpen).toBe(true);
    expect(togglePanel(hidden, "left")).toMatchObject(DEFAULT_LAYOUT);
    expect(togglePanel(DEFAULT_LAYOUT, "bottom").bottomOpen).toBe(true);
  });

  it("persists engineering and research layouts under separate keys", () => {
    const storage = new MemoryStorage();
    const engineering = { ...DEFAULT_LAYOUT, leftWidth: 330 };
    const research = { ...DEFAULT_LAYOUT, rightOpen: false };
    saveWorkspaceLayout("engineering", engineering, storage);
    saveWorkspaceLayout("research", research, storage);
    expect(storage.getItem(LAYOUT_STORAGE_KEYS.engineering)).toContain("330");
    expect(loadWorkspaceLayout("engineering", storage)).toMatchObject(engineering);
    expect(loadWorkspaceLayout("research", storage)).toMatchObject(research);
    expect(loadWorkspaceLayout("engineering", storage)).not.toMatchObject(research);
  });

  it("migrates the engineering v3 sidebars once while preserving bottom state", () => {
    const storage = new MemoryStorage();
    storage.setItem(LEGACY_ENGINEERING_LAYOUT_KEY, JSON.stringify({
      leftOpen: false,
      rightOpen: true,
      bottomOpen: true,
      leftWidth: 260,
      rightWidth: 410,
      bottomHeight: 360,
    }));

    const migrated = loadWorkspaceLayout("engineering", storage);
    expect(migrated).toEqual({
      leftOpen: true,
      rightOpen: false,
      bottomOpen: true,
      leftWidth: 410,
      rightWidth: 320,
      bottomHeight: 360,
    });
    expect(JSON.parse(storage.getItem(LAYOUT_STORAGE_KEYS.engineering) || "{}")).toEqual(migrated);

    storage.setItem(LEGACY_ENGINEERING_LAYOUT_KEY, JSON.stringify({ leftOpen: true, rightOpen: true, leftWidth: 420, rightWidth: 240 }));
    expect(loadWorkspaceLayout("engineering", storage)).toEqual(migrated);
  });

  it("keeps the independent research v3 layout unchanged", () => {
    const storage = new MemoryStorage();
    const research = { ...DEFAULT_LAYOUT, leftOpen: false, rightWidth: 505, bottomOpen: true };
    storage.setItem(LAYOUT_STORAGE_KEYS.research, JSON.stringify(research));
    expect(loadWorkspaceLayout("research", storage)).toEqual(research);
    expect(LAYOUT_STORAGE_KEYS.research).toBe("topoptpilot.layout.research.v3");
  });
  it("ignores malformed or narrow-screen layouts and can reset to defaults", () => {
    const storage = new MemoryStorage();
    storage.setItem(LAYOUT_STORAGE_KEYS.engineering, "not-json");
    expect(loadWorkspaceLayout("engineering", storage)).toEqual(DEFAULT_LAYOUT);
    const narrow: WorkspaceLayout = { ...DEFAULT_LAYOUT, leftWidth: 100, rightWidth: 100, bottomHeight: 50 };
    expect(clampLayout(narrow, { viewportWidth: 600 })).toMatchObject({ leftWidth: 240, rightWidth: 320, bottomHeight: 180 });
    saveWorkspaceLayout("engineering", { ...DEFAULT_LAYOUT, leftWidth: 340 }, storage);
    expect(resetWorkspaceLayout("engineering", storage)).toEqual(DEFAULT_LAYOUT);
    expect(loadWorkspaceLayout("engineering", storage)).toEqual(DEFAULT_LAYOUT);
  });
});

class MemoryStorage implements Storage {
  private values = new Map<string, string>();
  get length() { return this.values.size; }
  clear() { this.values.clear(); }
  getItem(key: string) { return this.values.get(key) ?? null; }
  key(index: number) { return Array.from(this.values.keys())[index] ?? null; }
  removeItem(key: string) { this.values.delete(key); }
  setItem(key: string, value: string) { this.values.set(key, value); }
}
