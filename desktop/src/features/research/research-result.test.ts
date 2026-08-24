import { describe, expect, it } from "vitest";
import { normalizeResearchField, normalizeResearchHistory } from "./research-result";

describe("research result normalization", () => {
  it("keeps 2D solver fields and projects 3D fields by maximum evidence", () => {
    expect(normalizeResearchField([[0.1, 0.2], [0.3, 0.4]])).toEqual([
      [0.1, 0.2],
      [0.3, 0.4],
    ]);
    expect(normalizeResearchField([
      [[0.1, 0.8], [0.3, 0.4]],
      [[0.5, 0.2], [0.9, 0.1]],
    ])).toEqual([
      [0.5, 0.8],
      [0.9, 0.4],
    ]);
  });

  it("keeps only finite iteration and compliance evidence", () => {
    expect(normalizeResearchHistory([
      { iteration: 1, compliance: 10 },
      { iteration: 2, compliance: "bad" },
      { iteration: 3, objective: 7.5 },
    ])).toEqual([
      { iteration: 1, compliance: 10 },
      { iteration: 3, compliance: 7.5 },
    ]);
  });
});
