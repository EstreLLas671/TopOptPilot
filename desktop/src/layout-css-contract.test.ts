// @ts-expect-error Vitest executes this contract test in Node; Vite does not bundle test files.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./v2.css", import.meta.url), "utf8");
const enhancementCss = readFileSync(new URL("./v2-enhancements.css", import.meta.url), "utf8");
const themeCss = readFileSync(new URL("./theme.css", import.meta.url), "utf8");

describe("four-pane layout CSS contract", () => {
  it("maps the resizable workspace to five explicit grid tracks", () => {
    expect(css).toMatch(
      /\.resizable-workspace\s*\{[^}]*grid-template-columns:\s*var\(--left-track\)\s+var\(--left-handle\)\s+minmax\(0,\s*1fr\)\s+var\(--right-handle\)\s+var\(--right-track\)/s,
    );
    expect(css).toMatch(
      /\.workspace-main-column\s*\{[^}]*grid-template-rows:\s*var\(--bottom-rows\)/s,
    );
  });

  it("never hides an open sidebar or inspector only because the viewport is narrow", () => {
    expect(css).not.toContain(".v2-inspector{display:none}");
    expect(css).not.toContain(".v2-sidebar{display:none}");
  });

  it("keeps the center track shrinkable in the final stylesheet", () => {
    expect(enhancementCss).toMatch(
      /\.resizable-workspace\s*\{[^}]*grid-template-columns:\s*var\(--left-track\)\s+var\(--left-handle\)\s+minmax\(0,\s*1fr\)\s+var\(--right-handle\)\s+var\(--right-track\)/s,
    );
  });

  it("stacks inspector sections vertically instead of overflowing sideways", () => {
    expect(enhancementCss).toMatch(
      /\.resizable-workspace\s+\.workspace-right\s*\{[^}]*flex-direction:\s*column/s,
    );
  });

  it("uses one typography scale and horizontal parameter actions", () => {
    expect(enhancementCss).toContain("--idesktop-font-base: 14px");
    expect(enhancementCss).toContain("--idesktop-font-control: 13px");
    expect(enhancementCss).toMatch(/body, button, input, select, textarea\s*\{[^}]*font-family:\s*var\(--idesktop-font-sans\)/s);
    expect(enhancementCss).toMatch(/\.parameter-dialog\s*>\s*footer button\s*\{[^}]*white-space:\s*nowrap[^}]*writing-mode:\s*horizontal-tb/s);
    expect(enhancementCss).toMatch(/\.engineering-center-shell\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,1fr\)/s);
    expect(enhancementCss).toMatch(/\.engineering-view-tabs\s*\{[^}]*height:\s*auto\s*!important/s);
  });

  it("uses the titlebar remainder for each kept-alive workspace", () => {
    expect(themeCss).toMatch(/\.workspace-mode-layer\s*\{[^}]*flex:\s*1\s+1\s+auto[^}]*min-height:\s*0[^}]*height:\s*auto[^}]*overflow:\s*hidden/s);
    expect(themeCss).toMatch(/\.workspace-mode-layer\s*>\s*\.v2-workspace\s*\{[^}]*height:\s*100%[^}]*min-height:\s*0/s);
  });

  it("does not reserve an empty assistant row on the engineering chat tab", () => {
    expect(enhancementCss).toMatch(/\.engineering-center-shell\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,1fr\)\s*!important/s);
    expect(enhancementCss).toMatch(/\.engineering-center-shell\.has-compact-assistant\s*\{[^}]*grid-template-rows:\s*auto\s+minmax\(0,1fr\)\s+auto\s*!important/s);
    expect(enhancementCss).not.toMatch(/\.engineering-center-shell\s*\{[^}]*82px/s);
  });
});
