import { describe, expect, it } from "vitest";
import { mergeTerminalResults, parseDensityCsv, parseHistoryJson } from "./artifact-viewer";

describe("engineering artifact viewer", () => {
  it("parses finite density values into a rectangular matrix", () => {
    expect(parseDensityCsv("0,0.5,1\n0.25,0.75,1\n")).toEqual([
      [0, 0.5, 1],
      [0.25, 0.75, 1],
    ]);
    expect(() => parseDensityCsv("0,NaN\n")).toThrow(/finite/i);
  });

  it("extracts convergence points from the real FEM history schema", () => {
    expect(parseHistoryJson('[{"iteration":1,"compliance":12.5},{"iteration":2,"compliance":9.25}]')).toEqual([
      { iteration: 1, compliance: 12.5 },
      { iteration: 2, compliance: 9.25 },
    ]);
  });

  it("deduplicates terminal poll results by command id", () => {
    const first = mergeTerminalResults([], new Set(), [{ id: 1, status: "completed", output: "ans = 2" }]);
    const second = mergeTerminalResults(first.lines, first.seenIds, [
      { id: 1, status: "completed", output: "ans = 2" },
      { id: 2, status: "failed", error: "MATLAB stopped" },
    ]);
    expect(second.lines).toEqual(["ans = 2", "[failed] MATLAB stopped"]);
  });
});
