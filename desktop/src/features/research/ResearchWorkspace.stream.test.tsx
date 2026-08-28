// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  researchArtifacts: vi.fn(),
  researchOptimizationConfig: vi.fn(),
  conversationList: vi.fn(),
  conversationCreate: vi.fn(),
  conversationMessages: vi.fn(),
  conversationMessage: vi.fn(),
  conversationAttachment: vi.fn(),
  researchChat: vi.fn(),
  researchEvents: vi.fn(),
  saveResearchHypothesis: vi.fn(),
  applyResearchSuggestion: vi.fn(),
  stream: vi.fn(),
}));

vi.mock("../../api", () => ({ api: apiMocks }));

import type { Research } from "../../types";
import { DEFAULT_OPTIMIZATION_CONFIG } from "../../optimization-config";
import ResearchWorkspace from "./ResearchWorkspace";

const research = {
  id: "R-ASYNC", name: "Async stream", goal: "Verify ticket stream", locale: "zh-CN",
  status: "READY", mode: "COPILOT", constraints: {}, budget_total: 4, budget_used: 0,
  experiments: [], events: [], decisions: [],
} as Research;

describe("ResearchWorkspace stream lifecycle", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.researchArtifacts.mockResolvedValue({ experiments: [] });
    apiMocks.researchOptimizationConfig.mockResolvedValue(DEFAULT_OPTIMIZATION_CONFIG);
    apiMocks.conversationList.mockResolvedValue([]);
    apiMocks.conversationCreate.mockResolvedValue({
      id: "research-chat-1", scope: "research", ownerId: research.id, title: "科研对话",
      createdAt: Date.now(), updatedAt: Date.now(),
    });
    apiMocks.conversationMessages.mockResolvedValue([]);
    apiMocks.conversationAttachment.mockResolvedValue({
      id: "research-attachment-1", fileName: "evidence.webp", mediaType: "image/webp",
      sizeBytes: 4, sha256: "b".repeat(64),
    });
    apiMocks.researchChat.mockResolvedValue({ reply: "科研回复", source: "qwen", contextDigest: "a".repeat(64) });
    apiMocks.researchEvents.mockResolvedValue([]);
    apiMocks.saveResearchHypothesis.mockResolvedValue({ ...research, hypothesis: "滤波半径会影响灰度率" });
    apiMocks.applyResearchSuggestion.mockResolvedValue({ research: { ...research, hypothesis: "滤波半径会影响灰度率" }, optimizationConfig: DEFAULT_OPTIMIZATION_CONFIG });
  });

  it("awaits the ticket-backed socket and closes the resolved socket on unmount", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const view = render(<ResearchWorkspace
      researches={[research]} selected={research} command="" busy={false} safeMode={true}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);

    await waitFor(() => expect(socket.onmessage).toBeTypeOf("function"));
    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1));
    view.unmount();
    expect(socket.close).toHaveBeenCalled();
  });

  it("routes normal chat through the non-SQLite research chat API", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    apiMocks.conversationMessage
      .mockResolvedValueOnce({ id: "msg-user", seq: 1, role: "user", content: "解释当前证据", attachmentIds: [], createdAt: Date.now() })
      .mockResolvedValueOnce({ id: "msg-agent", seq: 2, role: "assistant", content: "科研回复", attachmentIds: [], source: "qwen", createdAt: Date.now() });
    const onCommand = vi.fn();
    render(<ResearchWorkspace
      researches={[research]} selected={research} command="解释当前证据" busy={false} safeMode={false}
      onCommand={onCommand} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);

    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "发送科研消息" }));
    await waitFor(() => expect(apiMocks.researchChat).toHaveBeenCalledWith(research.id, "解释当前证据", undefined));
    expect(onCommand).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getByText("科研回复")).toBeTruthy());
  });
  it("accepts a dragged local image in the single research composer", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const onError = vi.fn();
    render(<ResearchWorkspace
      researches={[research]} selected={research} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={onError}
      onSelect={async () => undefined} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);

    const textarea = await screen.findByPlaceholderText("描述目标、询问证据或提出下一项实验…");
    await waitFor(() => expect(apiMocks.conversationMessages).toHaveBeenCalledWith("research-chat-1"));
    const composer = textarea.closest("footer");
    expect(composer).toBeTruthy();
    const file = new File([new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80])], "evidence.webp", { type: "" });
    const dataTransfer = { types: ["Files"], files: [file], dropEffect: "none" };

    fireEvent.dragEnter(composer!, { dataTransfer });
    expect(screen.getByText("松开以上传附件")).toBeTruthy();
    fireEvent.drop(composer!, { dataTransfer });

    await waitFor(() => expect(apiMocks.conversationAttachment).toHaveBeenCalledWith("research-chat-1", expect.objectContaining({ fileName: "evidence.webp", mediaType: "image/webp" })));
    expect(await screen.findByAltText("evidence.webp")).toBeTruthy();
    expect(onError).not.toHaveBeenCalled();
  });

  it("shows the research composer only on the conversation tab and restores it after audit", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    render(<ResearchWorkspace
      researches={[research]} selected={research} command="保留这段科研草稿" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);

    expect(await screen.findByDisplayValue("保留这段科研草稿")).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "过程 / 审计" }));
    expect(screen.queryByPlaceholderText("描述目标、询问证据或提出下一项实验…")).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "科研对话" }));
    expect(await screen.findByDisplayValue("保留这段科研草稿")).toBeTruthy();
  });
  it("renders exactly the four ordered research-state cards and saves a hypothesis", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const onSelect = vi.fn();
    const view = render(<ResearchWorkspace
      researches={[research]} selected={research} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={onSelect} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);
    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalled());
    const headings = Array.from(view.container.querySelectorAll(".workspace-right .inspector-card h4")).map(node => node.textContent);
    expect(headings).toEqual(["研究目标", "研究假设", "参数配置", "结果呈现"]);
    const hypothesis = screen.getByRole("textbox", { name: "研究假设" });
    fireEvent.change(hypothesis, { target: { value: "滤波半径会影响灰度率" } });
    fireEvent.click(screen.getByRole("button", { name: "保存假设" }));
    await waitFor(() => expect(apiMocks.saveResearchHypothesis).toHaveBeenCalledWith(research.id, "滤波半径会影响灰度率"));
    expect(onSelect).toHaveBeenCalledWith(research.id);
  });

  it("shows an agent research-state difference and applies it only after approval", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const action = {
      type: "apply_research_state" as const,
      hypothesis: "滤波半径会影响灰度率",
      changedFields: ["hypothesis"] as const,
      rationale: "基于当前实验趋势",
    };
    apiMocks.researchChat.mockResolvedValue({ reply: "建议如下。", source: "qwen", contextDigest: "a".repeat(64), actions: [action] });
    apiMocks.conversationMessage
      .mockResolvedValueOnce({ id: "msg-user-action", seq: 1, role: "user", content: "建议假设", attachmentIds: [], createdAt: Date.now() })
      .mockResolvedValueOnce({ id: "msg-agent-action", seq: 2, role: "assistant", content: "建议如下。", attachmentIds: [], source: "qwen", createdAt: Date.now() });
    render(<ResearchWorkspace
      researches={[research]} selected={research} command="建议假设" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined}
      setCommand={() => undefined}
    />);
    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "发送科研消息" }));
    expect(await screen.findByRole("region", { name: "Agent 研究状态建议" })).toBeTruthy();
    expect(apiMocks.applyResearchSuggestion).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "批准并填入" }));
    await waitFor(() => expect(apiMocks.applyResearchSuggestion).toHaveBeenCalledWith(research.id, action));
  });
});
