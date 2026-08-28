import type { AppSettings } from "./types";

type ThemeTokens = AppSettings["custom_theme"];
const light: ThemeTokens = {
  accent:"#2e73ca", accent_hover:"#245da5", background:"#f4f7fb", surface:"#ffffff",
  elevated:"#f8fbff", text:"#24344d", muted_text:"#6f8095", border:"#dce5ef",
  success:"#23835c", warning:"#b56b17", danger:"#c64242", chart:"#2e73ca",
  chart_grid:"#cbd7e5", volume_background:"#f1f5fa", contrast:100,
};
const dark: ThemeTokens = {
  accent:"#69a8f2", accent_hover:"#8bbcf5", background:"#0d131b", surface:"#151e29",
  elevated:"#1b2734", text:"#e4edf7", muted_text:"#9aabba", border:"#334354",
  success:"#58c794", warning:"#e4a653", danger:"#ef7272", chart:"#74aff3",
  chart_grid:"#34485d", volume_background:"#0b1118", contrast:100,
};
const colorKeys = [
  "accent", "accent_hover", "background", "surface", "elevated", "text", "muted_text",
  "border", "success", "warning", "danger", "chart", "chart_grid", "volume_background",
] as const;

export function resolvedThemeName(settings: AppSettings): "light" | "dark" | "custom" {
  const requested = settings.theme || "light";
  if (requested === "system") return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  return requested;
}

export function applyTheme(settings: AppSettings): void {
  const resolved = resolvedThemeName(settings);
  const configured = settings.custom_theme || light;
  const palette = resolved === "dark" ? dark : resolved === "custom" ? { ...light, ...configured } : light;
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.dataset.colorScheme = resolved === "dark" ? "dark" : "light";
  for (const token of colorKeys) {
    const value = String(palette[token] || light[token] || "#000000");
    root.style.setProperty(`--theme-${token.replaceAll("_", "-")}`, value);
    root.style.setProperty(`--custom-${token.replaceAll("_", "-")}`, value);
  }
  const contrast = Math.min(140, Math.max(80, Number(palette.contrast ?? 100)));
  root.style.setProperty("--theme-contrast", `${contrast}%`);
}