import type { AppSettings } from "./types";
import "./theme.css";

const tokens = ["accent", "background", "surface", "text"] as const;

export function applyTheme(settings: AppSettings): void {
  const requested = settings.theme || "light";
  const resolved = requested === "system"
    ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
    : requested;
  document.documentElement.dataset.theme = resolved;
  for (const token of tokens) {
    const property = `--custom-${token}`;
    if (resolved === "custom") document.documentElement.style.setProperty(property, settings.custom_theme[token]);
    else document.documentElement.style.removeProperty(property);
  }
}
