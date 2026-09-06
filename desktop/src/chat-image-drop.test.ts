// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { imageCandidateFromFile } from "./chat-image-drop";

function attachment(name: string, type: string, bytes: number[]): File {
  const payload = new Uint8Array(bytes);
  return {
    name,
    type,
    size: payload.byteLength,
    arrayBuffer: async () => payload.buffer,
  } as File;
}

describe("chat attachment format detection", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", {
      subtle: { digest: async () => new Uint8Array(32).buffer },
    });
  });

  it.each([
    ["paper.pdf", "application/pdf", [0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37]],
    ["notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", [0x50, 0x4b, 0x03, 0x04, 1]],
    ["table.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [0x50, 0x4b, 0x03, 0x04, 2]],
    ["shape.svg", "image/svg+xml", Array.from(new TextEncoder().encode("<svg xmlns='http://www.w3.org/2000/svg'></svg>"))],
    ["readme.txt", "text/plain", Array.from(new TextEncoder().encode("TopOptPilot attachment"))],
    ["values.csv", "text/csv", Array.from(new TextEncoder().encode("x,y\n1,2"))],
  ])("accepts %s by verified content", async (name, type, bytes) => {
    const candidate = await imageCandidateFromFile(attachment(name, type, bytes));
    expect(candidate.mediaType).toBe(type);
    expect(candidate.fileName).toBe(name);
    expect(candidate.preview).toBe("");
  });

  it("rejects a document whose content does not match its extension", async () => {
    await expect(imageCandidateFromFile(attachment("fake.pdf", "application/pdf", [1, 2, 3])))
      .rejects.toThrow("文件内容与扩展名不一致");
  });
});