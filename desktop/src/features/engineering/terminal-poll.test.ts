import { describe, expect, it } from "vitest";
import { mergeTerminalResults } from "./artifact-viewer";

describe("terminal polling stability", () => {
  it("reuses the existing line array when a poll has no new command results", () => {
    const lines = ["> disp(1)", "1"];
    const merged = mergeTerminalResults(lines, new Set([1]), [{ id: 1, status: "completed", output: "1" }]);
    expect(merged.lines).toBe(lines);
  });
});
