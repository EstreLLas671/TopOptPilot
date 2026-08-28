// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { applyTheme } from "./theme";
import type { AppSettings } from "./types";

const settings = {
  theme: "custom",
  custom_theme: { accent: "#123456", background: "#eeeeee", surface: "#ffffff", text: "#222222" },
} as AppSettings;

describe("semantic theme application", () => {
  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-color-scheme");
    document.documentElement.removeAttribute("style");
  });

  it("deep-merges legacy four-token custom themes with semantic defaults", () => {
    applyTheme(settings);
    expect(document.documentElement.dataset.theme).toBe("custom");
    expect(document.documentElement.style.getPropertyValue("--theme-accent")).toBe("#123456");
    expect(document.documentElement.style.getPropertyValue("--theme-border")).toBe("#dce5ef");
    expect(document.documentElement.style.getPropertyValue("--theme-contrast")).toBe("100%");
  });

  it("applies the complete dark preset independently of custom colors", () => {
    applyTheme({ ...settings, theme: "dark" });
    expect(document.documentElement.dataset.colorScheme).toBe("dark");
    expect(document.documentElement.style.getPropertyValue("--theme-background")).toBe("#0d131b");
    expect(document.documentElement.style.getPropertyValue("--theme-volume-background")).toBe("#0b1118");
  });
});
