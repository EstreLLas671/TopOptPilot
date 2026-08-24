import { describe, expect, it } from "vitest";
import { matlabLanguageDefinition, matlabLanguageRegistration } from "./matlab-language";

describe("MATLAB Monaco language", () => {
  it("registers .m files and recognizes core MATLAB syntax", () => {
    expect(matlabLanguageRegistration).toMatchObject({ id: "matlab", extensions: [".m"] });
    expect(matlabLanguageDefinition.keywords).toContain("function");
    expect(matlabLanguageDefinition.keywords).toContain("end");
    expect(matlabLanguageDefinition.tokenizer.root).toEqual(expect.arrayContaining([
      [/%.*$/, "comment"],
      [/[a-zA-Z_]\w*/, { cases: { "@keywords": "keyword", "@default": "identifier" } }],
    ]));
  });
});
