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
  engineeringComparisonSchemes: vi.fn(),
  researchImportEngineeringScheme: vi.fn(),
  researchVisualization: vi.fn(),
  researchVisualizationField: vi.fn(),
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
    apiMocks.engineeringComparisonSchemes.mockResolvedValue([]);
    apiMocks.researchVisualization.mockResolvedValue({
      researchId: research.id, experimentId: "E01", dimension: "2d", shape: [2, 2, 1],
      encoding: "float32-le", order: "F", hasStress: false, history: [{ iteration: 1, compliance: 10 }],
      metrics: { compliance: 10, volumeFraction: .4, grayRatio: .1, connectedComponents: 1 },
      config: { dimension: "2d", nelx: 2, nely: 2 }, backend: "matlab", fidelity: "F0", status: "SUCCESS",
      evidenceIds: ["AR-REAL"], resultSource: "LIVE_REAL_RUN",
    });
    apiMocks.researchVisualizationField.mockResolvedValue(new Float32Array([.1, .2, .3, .4]).buffer);
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
    expect(apiMocks.conversationCreate).not.toHaveBeenCalled();
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

    fireEvent.click(screen.getByRole("button", { name: "发送科研消息" }));
    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1));
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
    expect(apiMocks.conversationCreate).not.toHaveBeenCalled();
    const chatRegion = textarea.closest(".research-chat-main");
    expect(chatRegion).toBeTruthy();
    const file = new File([new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80])], "evidence.webp", { type: "" });
    const dataTransfer = { types: ["Files"], files: [file], dropEffect: "none" };

    fireEvent.dragEnter(chatRegion!, { dataTransfer });
    expect(screen.getByText("松开以上传附件")).toBeTruthy();
    fireEvent.drop(chatRegion!, { dataTransfer });

    await waitFor(() => expect(apiMocks.conversationAttachment).toHaveBeenCalledWith("research-chat-1", expect.objectContaining({ fileName: "evidence.webp", mediaType: "image/webp" })));
    expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1);
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
    expect(apiMocks.conversationCreate).not.toHaveBeenCalled();
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
    fireEvent.click(screen.getByRole("button", { name: "发送科研消息" }));
    await waitFor(() => expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("region", { name: "Agent 研究状态建议" })).toBeTruthy();
    expect(apiMocks.applyResearchSuggestion).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "批准并填入" }));
    await waitFor(() => expect(apiMocks.applyResearchSuggestion).toHaveBeenCalledWith(research.id, action));
  });

  it("imports a verified completed engineering scheme without starting research", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const scheme = {
      id: "scheme-1", name: "工程方案一", runId: "run-1", configDigest: "a".repeat(64), createdAt: "2026-08-29T00:00:00Z",
      integrity: "verified", integrityFailures: [], config: { dimension: "3d" },
      run: { runId: "run-1", status: "completed", lane: "local-matlab", ownerId: "P1", configDigest: "a".repeat(64),
        metrics: { compliance: 12, volumeFraction: .4, grayRatio: .02 }, snapshots: [], files: [{}],
        provenance: { resultKind: "solver", backend: "local-matlab" } },
    };
    apiMocks.engineeringComparisonSchemes.mockResolvedValue([scheme]);
    apiMocks.researchImportEngineeringScheme.mockResolvedValue({
      research, optimizationConfig: DEFAULT_OPTIMIZATION_CONFIG,
      baseline: { schemeId: scheme.id, name: scheme.name, runId: scheme.runId, configDigest: scheme.configDigest,
        metrics: scheme.run.metrics, provenance: scheme.run.provenance, importedFrom: "engineering-comparison-scheme" },
    });
    apiMocks.conversationMessage.mockResolvedValue({ id: "baseline-system", seq: 1, role: "system", content: "已导入工程方案", attachmentIds: [], createdAt: Date.now() });
    render(<ResearchWorkspace
      researches={[research]} selected={research} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "导入工程方案" }));
    expect(await screen.findByRole("dialog", { name: "导入工程方案" })).toBeTruthy();
    expect(screen.getByText("工程方案一")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "导入并填入" }));
    await waitFor(() => expect(apiMocks.researchImportEngineeringScheme).toHaveBeenCalledWith(research.id, scheme.id));
    expect(apiMocks.conversationCreate).toHaveBeenCalledTimes(1);
    expect(apiMocks.conversationMessage).toHaveBeenCalledWith("research-chat-1", expect.objectContaining({ role: "system", source: "engineering-baseline" }));
  });

  it("renders current-round workflow progress and detailed step evidence", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const withWorkflow = { ...research, workflow: {
      round: 2, stage: "experiments" as const, percent: 44, budgetUsed: 2, budgetTotal: 4,
      steps: [{ id: "experiments", label: "执行三套真实实验", status: "active" as const,
        result: "已完成 1 / 3 个真实方案", reflection: "失败方案不补造指标", evidenceIds: ["E02"], experimentIds: ["E02"], nextAction: "等待真实终态" }],
    } };
    render(<ResearchWorkspace
      researches={[withWorkflow]} selected={withWorkflow} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}
    />);
    expect(await screen.findByLabelText("自主研究阶段进度")).toBeTruthy();
    expect(screen.getAllByText("第 2 轮").length).toBeGreaterThan(0);
    expect(screen.getAllByText("44%").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "显示底部面板" }));
    expect(screen.getByText("已完成 1 / 3 个真实方案")).toBeTruthy();
    expect(screen.getByText("失败方案不补造指标")).toBeTruthy();
  });

  it("reopens a persisted real final experiment in the result dialog", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const experiment = { id: "E01", research_id: research.id, purpose: "真实基线", fidelity: "F0", mesh_level: "coarse",
      backend: "matlab", parameters: { dimension: "2d", nelx: 2, nely: 2 }, status: "SUCCESS", progress: 1,
      current_iteration: 1, result: { objective: { compliance: 10 }, constraints: { volume_fraction: .4 }, quality: { gray_ratio: .1, connected_components: 1 }, artifacts: {} } } as any;
    const withResult = { ...research, experiments: [experiment], best_experiment: experiment };
    render(<ResearchWorkspace
      researches={[withResult]} selected={withResult} active={experiment} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}
    />);
    fireEvent.click(await screen.findByRole("button", { name: "查看最终方案" }));
    expect(await screen.findByRole("dialog", { name: "科研最终方案详情" })).toBeTruthy();
    await waitFor(() => expect(apiMocks.researchVisualization).toHaveBeenCalledWith(research.id, experiment.id));
    expect(await screen.findByText("真实密度")).toBeTruthy();
    expect(screen.getByText("AR-REAL")).toBeTruthy();
  });

  it("prevents starting another autonomous round while the research is running", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const running = { ...research, status: "RUNNING" };
    render(<ResearchWorkspace
      researches={[running]} selected={running} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined}
      onArchive={async () => undefined} onRestore={async () => undefined}
      onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}
    />);
    expect(screen.getByRole("button", { name: "运行自主研究" }).hasAttribute("disabled")).toBe(true);
  });

  it("auto-opens a persisted final result only once across workspace remounts", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const experiment = { id: "E-AUTO-ONCE", research_id: "R-AUTO-ONCE", purpose: "最终方案", fidelity: "F0",
      mesh_level: "coarse", backend: "python", parameters: { dimension: "2d", nelx: 2, nely: 2 },
      status: "SUCCESS", progress: 1, current_iteration: 1,
      result: { objective: { compliance: 10 }, constraints: { volume_fraction: .4 }, quality: { gray_ratio: .1, connected_components: 1 }, artifacts: {} } } as any;
    const completed = { ...research, id: "R-AUTO-ONCE", status: "STOPPED", experiments: [experiment], best_experiment: experiment };
    const props = {
      researches: [completed], selected: completed, command: "", busy: false, safeMode: false,
      onCommand: () => undefined, onCreateResearch: () => undefined,
      onArchive: async () => undefined, onRestore: async () => undefined,
      onDecision: () => undefined, onError: () => undefined,
      onSelect: async () => undefined, onSelectExperiment: () => undefined, setCommand: () => undefined,
    };
    const first = render(<ResearchWorkspace {...props}/>);
    expect(await screen.findByRole("dialog", { name: "科研最终方案详情" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "关闭科研方案详情" }));
    first.unmount();
    render(<ResearchWorkspace {...props}/>);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "科研最终方案详情" })).toBeNull());
  });
});
