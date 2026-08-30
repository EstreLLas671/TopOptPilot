// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  engineeringChat: vi.fn(),
  conversationList: vi.fn(),
  conversationCreate: vi.fn(),
  conversationMessages: vi.fn(),
  conversationMessage: vi.fn(),
  conversationDelete: vi.fn(),
  conversationAttachment: vi.fn(),
}));
vi.mock("../../api", () => ({ api: apiMocks }));

import EngineeringChatPanel from "./EngineeringChatPanel";
import { DEFAULT_OPTIMIZATION_CONFIG } from "../../optimization-config";

const selectedFile = { relative_path: "solver/example.m", content: "secret source", sha256: "0".repeat(64) };

describe("EngineeringChatPanel", () => {
  beforeEach(() => {
    apiMocks.conversationList.mockResolvedValue([]);
    apiMocks.conversationCreate.mockResolvedValue({
      id: "conversation-1", scope: "engineering", ownerId: "project-1",
      title: "工程对话", createdAt: "2026-08-26T00:00:00Z", updatedAt: "2026-08-26T00:00:00Z",
    });
    apiMocks.conversationMessages.mockResolvedValue([]);
    apiMocks.conversationMessage.mockImplementation(async (_id, data) => ({
      id: data.role + "-message", seq: data.role === "user" ? 1 : 2,
      createdAt: "2026-08-26T00:00:00Z", ...data,
    }));
    apiMocks.conversationDelete.mockResolvedValue({ deleted: true, id: "conversation-1" });
  });
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("does not send file source until the user explicitly consents", async () => {
    apiMocks.engineeringChat.mockResolvedValue({ reply: "未配置", source: "not_configured", actions: [], contextDigest: "digest" });
    render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} />);
    await screen.findByPlaceholderText("询问当前工程、参数或结果…");
    await userEvent.type(screen.getByPlaceholderText("询问当前工程、参数或结果…"), "解释参数");
    await userEvent.click(screen.getByRole("button", { name: "发送聊天消息" }));
    await waitFor(() => expect(apiMocks.engineeringChat).toHaveBeenCalledTimes(1));
    expect(apiMocks.engineeringChat.mock.calls[0][0].allowExternalSource).toBe(false);
    expect(apiMocks.engineeringChat.mock.calls[0][0].context).not.toHaveProperty("source");
    expect(await screen.findByText("未配置 Qwen")).toBeTruthy();
  });

  it("sends only the current file after consent", async () => {
    apiMocks.engineeringChat.mockResolvedValue({ reply: "解释", source: "qwen", actions: [], contextDigest: "digest" });
    render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} />);
    await screen.findByPlaceholderText("询问当前工程、参数或结果…");
    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.type(screen.getByPlaceholderText("询问当前工程、参数或结果…"), "解释代码");
    await userEvent.click(screen.getByRole("button", { name: "发送聊天消息" }));
    await waitFor(() => expect(apiMocks.engineeringChat).toHaveBeenCalledTimes(1));
    expect(apiMocks.engineeringChat.mock.calls[0][0].allowExternalSource).toBe(true);
    expect(apiMocks.engineeringChat.mock.calls[0][0].context.source).toBe("secret source");
  });
  it("uploads a dragged local image through the existing attachment boundary", async () => {
    apiMocks.conversationAttachment.mockResolvedValue({
      id: "attachment-1", fileName: "structure.png", mediaType: "image/png",
      sizeBytes: 4, sha256: "a".repeat(64),
    });
    const onError = vi.fn();
    render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={onError} />);
    const textarea = await screen.findByPlaceholderText("询问当前工程、参数或结果…");
    expect(apiMocks.conversationCreate).not.toHaveBeenCalled();
    const chatRegion = textarea.closest(".engineering-chat-panel");
    expect(chatRegion).toBeTruthy();
    const file = new File([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], "structure.png", { type: "" });
    const dataTransfer = {
      types: ["Files"],
      items: [{ kind: "file", getAsFile: () => file }],
      files: [],
      dropEffect: "none",
    };

    fireEvent.dragEnter(chatRegion!, { dataTransfer });
    expect(screen.getByText("松开以上传附件")).toBeTruthy();
    fireEvent.drop(chatRegion!, { dataTransfer });

    await waitFor(() => expect(apiMocks.conversationAttachment).toHaveBeenCalledTimes(1));
    expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1);
    expect(apiMocks.conversationAttachment.mock.calls[0][0]).toBe("conversation-1");
    expect(apiMocks.conversationAttachment.mock.calls[0][1]).toMatchObject({ fileName: "structure.png", mediaType: "image/png" });
    expect(await screen.findByAltText("structure.png")).toBeTruthy();
    expect(onError).not.toHaveBeenCalled();
  });

  it("keeps the last selected conversation when an older request finishes late", async () => {
    const conversation = (id: string) => ({ id, scope: "engineering" as const, ownerId: "project-1", title: id, createdAt: 1, updatedAt: 1 });
    const resolvers = new Map<string, (value: unknown[]) => void>();
    apiMocks.conversationList.mockResolvedValue([conversation("conversation-a"), conversation("conversation-b")]);
    apiMocks.conversationMessages.mockImplementation((id: string) => new Promise(resolve => resolvers.set(id, resolve)));
    const view = render(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} requestedConversationId="conversation-a"/>);
    await waitFor(() => expect(resolvers.has("conversation-a")).toBe(true));
    view.rerender(<EngineeringChatPanel projectId="project-1" selectedFile={selectedFile} run={null} config={DEFAULT_OPTIMIZATION_CONFIG} onError={() => undefined} requestedConversationId="conversation-b"/>);
    await waitFor(() => expect(resolvers.has("conversation-b")).toBe(true));
    resolvers.get("conversation-b")?.([{ id: "message-b", seq: 1, role: "assistant", content: "最后选择的会话", attachmentIds: [], attachments: [], createdAt: 2 }]);
    expect(await screen.findByText("最后选择的会话")).toBeTruthy();
    resolvers.get("conversation-a")?.([{ id: "message-a", seq: 1, role: "assistant", content: "过期会话内容", attachmentIds: [], attachments: [], createdAt: 1 }]);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(screen.queryByText("过期会话内容")).toBeNull();
    expect(screen.getByText("最后选择的会话")).toBeTruthy();
  });
});
