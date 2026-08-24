// @ts-expect-error Vitest executes this contract test in Node; Vite does not bundle test files.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./v2.css", import.meta.url), "utf8");

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
});