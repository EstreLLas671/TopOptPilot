// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
const engineeringChat = vi.hoisted(() => vi.fn());
vi.mock("../../api", () => ({ api: { engineeringChat } }));
import EngineeringChatPanel from "./EngineeringChatPanel";
import { DEFAULT_OPTIMIZATION_CONFIG } from "../../optimization-config";
const selectedFile = { relative_path: "solver/example.m", content: "secret source", sha256: "0".repeat(64) };
describe("EngineeringChatPanel", () => {
  afterEach(() => { cleanup(); vi.clearAllMocks(); });
  it("does not send file source until the user explicitly consents", async () => {
    engineeringChat.mockResolvedValue({ reply: "未配置", source: "not_configured", actions: [], contextDigest: "digest" });
    render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} />);
    await userEvent.type(screen.getByPlaceholderText("询问当前工程、参数或结果…"), "解释参数");
    await userEvent.click(screen.getByRole("button", { name: "发送聊天消息" }));
    await waitFor(() => expect(engineeringChat).toHaveBeenCalledTimes(1));
    expect(engineeringChat.mock.calls[0][0].allowExternalSource).toBe(false);
    expect(engineeringChat.mock.calls[0][0].context).not.toHaveProperty("source");
    expect(screen.getByText(/Safe Mode/)).toBeTruthy();
  });
  it("sends only the current file after consent", async () => {
    engineeringChat.mockResolvedValue({ reply: "解释", source: "qwen", actions: [], contextDigest: "digest" });
    render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} />);
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.type(screen.getByPlaceholderText("询问当前工程、参数或结果…"), "解释代码");
    await userEvent.click(screen.getByRole("button", { name: "发送聊天消息" }));
    await waitFor(() => expect(engineeringChat).toHaveBeenCalledTimes(1));
    expect(engineeringChat.mock.calls[0][0].allowExternalSource).toBe(true);
    expect(engineeringChat.mock.calls[0][0].context.source).toBe("secret source");
  });
});