import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT,
  LAYOUT_STORAGE_KEYS,
  clampLayout,
  loadWorkspaceLayout,
  resetWorkspaceLayout,
  saveWorkspaceLayout,
  togglePanel,
  type WorkspaceLayout,
} from "./layout-state";

describe("workspace layout state", () => {
  it("uses the compact iDeskTop defaults", () => {
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
