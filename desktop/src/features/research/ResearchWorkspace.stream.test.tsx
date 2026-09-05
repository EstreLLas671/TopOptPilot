// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  researchVisionChat: vi.fn(),
  researchSuggestionExtract: vi.fn(),
  researchEvents: vi.fn(),
  autonomous: vi.fn(),
  stopAutonomous: vi.fn(),
  confirmResearchCandidatePlan: vi.fn(),
  finishResearch: vi.fn(),
  researchReportPreview: vi.fn(),
  getResearch: vi.fn(),
  saveResearchGoal: vi.fn(),
  saveResearchHypothesis: vi.fn(),
  saveResearchOptimizationConfig: vi.fn(),
  applyResearchSuggestion: vi.fn(),
  engineeringComparisonSchemes: vi.fn(),
  researchImportEngineeringScheme: vi.fn(),
  researchVisualization: vi.fn(),
  researchVisualizationField: vi.fn(),
  researchFidelityStageDecision: vi.fn(),
  stream: vi.fn(),
}));

vi.mock("../../api", () => ({ api: apiMocks }));

import type { Research } from "../../types";
import { DEFAULT_OPTIMIZATION_CONFIG } from "../../optimization-config";
import ResearchWorkspace from "./ResearchWorkspace";

const research = {
  id: "R-ASYNC", name: "Async stream", goal: "Verify ticket stream", hypothesis: "候选方向会产生不同证据", locale: "zh-CN",
  status: "READY", mode: "COPILOT", constraints: {}, budget_total: 4, budget_used: 0,
  experiments: [], events: [], decisions: [],
} as Research;

describe("ResearchWorkspace stream lifecycle", () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); });
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(window, "confirm").mockReturnValue(true);
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
    apiMocks.researchSuggestionExtract.mockResolvedValue({ reply: "异步科研回复", sourceId: "event:1", actions: [] });
    apiMocks.researchEvents.mockResolvedValue([]);
    apiMocks.autonomous.mockResolvedValue({ ...research, status: "RUNNING" });
    apiMocks.stopAutonomous.mockResolvedValue({ ...research, status: "STOPPING", termination_reason: "USER_STOPPED" });
    apiMocks.confirmResearchCandidatePlan.mockResolvedValue({ ...research, status: "RUNNING" });
    apiMocks.finishResearch.mockResolvedValue({ ...research, status: "STOPPED", termination_reason: "USER_FINISHED" });
    apiMocks.getResearch.mockResolvedValue({ ...research, status: "STOPPED", termination_reason: "USER_FINISHED" });
    apiMocks.researchReportPreview.mockResolvedValue({ markdown: "# 最终科研报告\n\n未完成步骤如实记录。", markdownPath: "report.md", pdfPath: "report.pdf" });
    apiMocks.saveResearchGoal.mockResolvedValue({ ...research, goal: "新的研究目标" });
    apiMocks.saveResearchHypothesis.mockResolvedValue({ ...research, hypothesis: "滤波半径会影响灰度率" });
    apiMocks.saveResearchOptimizationConfig.mockResolvedValue(DEFAULT_OPTIMIZATION_CONFIG);
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
    apiMocks.researchFidelityStageDecision.mockResolvedValue(research);
  });

  it("shows a completed Step result with topology, convergence and explicit choices", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const experiment = { id:"E01", research_id:research.id, purpose:"Step2", fidelity:"Step2", mesh_level:"coarse", backend:"python", status:"SUCCESS", progress:1, current_iteration:2, parameters:{}, result:{ objective:{compliance:12.5}, constraints:{volume_fraction:.4}, quality:{gray_ratio:.02,connected_components:1}, artifacts:{density:[[.1,.9],[.8,.2]],history:[{iteration:1,compliance:20},{iteration:2,compliance:12.5}]}} } as any;
    const failedWithPartialMetrics = { ...experiment, id:"E02", status:"FAILED", error:"solver failed after partial output", result:{...experiment.result, objective:{compliance:99}} } as any;
    const gated = { ...research, constraints:{volume_fraction:.4,gray_max:.05,connected:true}, experiments:[experiment,failedWithPartialMetrics], events: [{
      id: 41, kind: "HUMAN", title: "FIDELITY_STAGE_AWAITING_DECISION", body: "F1 完成", created_at: new Date().toISOString(),
      payload: { stage_code: "F1", internal_fidelity: "F0", round: 1, experiment_ids: ["E01","E02"], best_experiment_id: "E01", result: { successful: 1, failed: 1, best_compliance: 12.5 } },
    }] } as Research;
    render(<ResearchWorkspace researches={[gated]} selected={gated} active={experiment} command="" busy={false} safeMode={true}
      onCommand={() => undefined} onCreateResearch={() => undefined} onArchive={async () => undefined}
      onRestore={async () => undefined} onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}/>);
    expect(await screen.findByRole("dialog", { name: "Step2 阶段结果" })).toBeTruthy();
    expect(screen.getByText("推荐方案拓扑")).toBeTruthy();
    expect(screen.getAllByText("柔度收敛").length).toBeGreaterThan(0);
    expect(screen.queryByText("真实实验")).toBeNull();
    expect((screen.getByRole("radio", { name:/E02/ }) as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "以所选方案进入下一 Step" }).hasAttribute("disabled")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "重新生成三套对比方案" }));
    await waitFor(() => expect(apiMocks.researchFidelityStageDecision).toHaveBeenCalledWith(research.id, "REPEAT_STAGE", undefined));
  });

  it("uses the final Step4 choices without a second pre-run approval", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const experiment = { id:"E04", research_id:research.id, purpose:"Step4", fidelity:"Step4", mesh_level:"fine3d", backend:"matlab", status:"SUCCESS", progress:1, current_iteration:1, parameters:{}, result:{ objective:{compliance:8}, constraints:{volume_fraction:.4}, quality:{gray_ratio:.01,connected_components:1}, artifacts:{density:[[1]],history:[{iteration:1,compliance:8}]}} } as any;
    const gated = { ...research, experiments:[experiment], events:[{id:44,kind:"HUMAN",title:"FIDELITY_STAGE_AWAITING_DECISION",body:"Step4 完成",created_at:new Date().toISOString(),payload:{stage_code:"STEP4",round:4,experiment_ids:["E04"],best_experiment_id:"E04",result:{successful:1,failed:0,best_compliance:8}}}] } as Research;
    render(<ResearchWorkspace researches={[gated]} selected={gated} active={experiment} command="" busy={false} safeMode={true} onCommand={()=>undefined} onCreateResearch={()=>undefined} onArchive={async()=>undefined} onRestore={async()=>undefined} onDecision={()=>undefined} onError={()=>undefined} onSelect={async()=>undefined} onSelectExperiment={()=>undefined} setCommand={()=>undefined}/>);
    expect(await screen.findByRole("dialog", {name:"Step4 阶段结果"})).toBeTruthy();
    fireEvent.click(screen.getByRole("button", {name:"结束实验并生成报告"}));
    await waitFor(()=>expect(apiMocks.finishResearch).toHaveBeenCalledWith(research.id));
    expect(await screen.findByRole("dialog", {name:"最终科研报告"})).toBeTruthy();
  });

  it("shows three Step1 previews, marks the Agent recommendation, and submits all after preference confirmation", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const proposals = [1,2,3].map(index => ({ id:`P0${index}`, intent:`DIRECTION_${index}`, purpose:`候选方向 ${index}`, fidelity:"Step1", backend:"python", parameters:{beta:index}, risk:"LOW", safety_status:"APPROVED", controlled_factors:[`factor-${index}`], status:"PREVIEW" }));
    const planned = { ...research, proposals, defaults:{autonomous_workflow:{candidate_plan:{status:"AWAITING_CONFIRMATION",proposal_ids:proposals.map(item=>item.id),recommended_proposal_id:"P01"}}} } as Research;
    render(<ResearchWorkspace researches={[planned]} selected={planned} command="" busy={false} safeMode={true} onCommand={()=>undefined} onCreateResearch={()=>undefined} onArchive={async()=>undefined} onRestore={async()=>undefined} onDecision={()=>undefined} onError={()=>undefined} onSelect={async()=>undefined} onSelectExperiment={()=>undefined} setCommand={()=>undefined}/>);
    expect(await screen.findByRole("dialog", {name:"Step1 候选方案"})).toBeTruthy();
    expect(screen.getByText("Agent 推荐")).toBeTruthy();
    fireEvent.click(screen.getByText("候选方向 2"));
    fireEvent.click(screen.getByRole("button", {name:"确认偏好并运行全部三方案"}));
    await waitFor(()=>expect(apiMocks.confirmResearchCandidatePlan).toHaveBeenCalledWith(research.id,"P02"));
  });

  it("blocks autonomous start until both persisted fields match the drafts", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const missing = { ...research, hypothesis:null } as Research;
    const onError = vi.fn();
    render(<ResearchWorkspace researches={[missing]} selected={missing} command="" busy={false} safeMode={true} onCommand={()=>undefined} onCreateResearch={()=>undefined} onArchive={async()=>undefined} onRestore={async()=>undefined} onDecision={()=>undefined} onError={onError} onSelect={async()=>undefined} onSelectExperiment={()=>undefined} setCommand={()=>undefined}/>);
    const start=screen.getByRole("button",{name:"运行自主研究"});
    expect(start.getAttribute("data-unsaved-research-state")).toBe("true");
    expect((start as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(start);
    expect(onError).toHaveBeenCalledWith("请先保存研究目标和研究假设");
    expect(apiMocks.autonomous).not.toHaveBeenCalled();
  });

  it("renders a live Step4 MATLAB 3D density snapshot in the research result panel", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const experiment = { id:"E-LIVE-4", purpose:"Step4 verification", fidelity:"Step4", backend:"matlab", status:"RUNNING", progress:.4, current_iteration:4, parameters:{}, result:{ objective:{}, constraints:{}, quality:{}, artifacts:{ density:[[.1,.9],[.8,.2]], density_3d_live:[[[.1,.9],[.8,.2]],[[.3,.7],[.6,.4]]], history:[{iteration:4,compliance:9.2}] } } } as any;
    const running={...research,status:"RUNNING",experiments:[experiment]} as Research;
    render(<ResearchWorkspace researches={[running]} selected={running} active={experiment} command="" busy={false} safeMode={true} onCommand={()=>undefined} onCreateResearch={()=>undefined} onArchive={async()=>undefined} onRestore={async()=>undefined} onDecision={()=>undefined} onError={()=>undefined} onSelect={async()=>undefined} onSelectExperiment={()=>undefined} setCommand={()=>undefined}/>);
    expect(await screen.findByLabelText("可旋转缩放的三维密度场")).toBeTruthy();
    expect(screen.getByText(/当前优化结果 · E-LIVE-4/)).toBeTruthy();
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
    expect(Array.from(view.container.querySelectorAll(".research-state-heading"))).toHaveLength(4);
    expect(view.container.textContent).not.toContain("OPTIMIZATION");
    const hypothesis = screen.getByRole("textbox", { name: "研究假设" });
    fireEvent.change(hypothesis, { target: { value: "滤波半径会影响灰度率" } });
    fireEvent.click(screen.getByRole("button", { name: "保存假设" }));
    await waitFor(() => expect(apiMocks.saveResearchHypothesis).toHaveBeenCalledWith(research.id, "滤波半径会影响灰度率"));
    expect(onSelect).toHaveBeenCalledWith(research.id);
  });

  it("preserves sibling drafts across saves, refreshes, and research switches", async () => {
    const socket = { onmessage: null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    const first = { ...research, hypothesis: "已保存假设" };
    const second = { ...research, id: "R-SECOND", name: "Second", goal: "第二目标", hypothesis: "第二假设" };
    const props = {
      researches: [first, second], command: "", busy: false, safeMode: false,
      onCommand: () => undefined, onCreateResearch: () => undefined,
      onArchive: async () => undefined, onRestore: async () => undefined,
      onDecision: () => undefined, onError: () => undefined,
      onSelect: async () => undefined, onSelectExperiment: () => undefined, setCommand: () => undefined,
    };
    const view = render(<ResearchWorkspace {...props} selected={first}/>);
    fireEvent.change(screen.getByRole("textbox", { name: "研究假设" }), { target: { value: "未保存假设草稿" } });
    fireEvent.change(screen.getByRole("textbox", { name: "研究目标" }), { target: { value: "新的研究目标" } });
    fireEvent.click(screen.getByRole("button", { name: "保存目标" }));
    await waitFor(() => expect(apiMocks.saveResearchGoal).toHaveBeenCalledWith(first.id, "新的研究目标"));
    view.rerender(<ResearchWorkspace {...props} selected={{ ...first, goal: "新的研究目标" }}/>);
    expect((screen.getByRole("textbox", { name: "研究假设" }) as HTMLTextAreaElement).value).toBe("未保存假设草稿");
    view.rerender(<ResearchWorkspace {...props} selected={second}/>);
    expect(await screen.findByDisplayValue("第二假设")).toBeTruthy();
    view.rerender(<ResearchWorkspace {...props} selected={{ ...first, goal: "新的研究目标" }}/>);
    expect(await screen.findByDisplayValue("未保存假设草稿")).toBeTruthy();
  });

  it("asks before overwriting and leaves the extracted state as an unsaved draft", async () => {
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
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(apiMocks.applyResearchSuggestion).not.toHaveBeenCalled();
    expect((screen.getByRole("textbox", { name: "研究假设" }) as HTMLTextAreaElement).value).toBe("滤波半径会影响灰度率");
    expect(screen.getByRole("button", { name: "运行自主研究" }).getAttribute("data-unsaved-research-state")).toBe("true");
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
    const showBottom=screen.queryByRole("button", { name: "显示底部面板" });
    if(showBottom) fireEvent.click(showBottom);
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

  it("turns the autonomous button into a stop action while research is running", async () => {
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
    const stop = screen.getByRole("button", { name: "停止自主研究" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fireEvent.click(stop);
    await waitFor(() => expect(apiMocks.stopAutonomous).toHaveBeenCalledWith(research.id));
  });

  it("extracts and queues editable suggestions from asynchronous visible Agent replies", async () => {
    const socket = { onmessage: null as ((event: MessageEvent) => void) | null, onerror: null, close: vi.fn() } as unknown as WebSocket;
    apiMocks.stream.mockResolvedValue(socket);
    apiMocks.conversationList.mockResolvedValue([{ id: "persisted-chat", scope: "research", ownerId: research.id, title: "科研对话", createdAt: 1, updatedAt: 1 }]);
    const action = { type: "apply_research_state" as const, goal: "降低柔度", changedFields: ["goal"] as const, rationale: "异步建议" };
    apiMocks.researchSuggestionExtract.mockResolvedValue({ reply: "建议将目标改为降低柔度。", sourceId: "event:91", actions: [action] });
    apiMocks.conversationMessage.mockResolvedValue({ id: "msg-pi-91", seq: 3, role: "assistant", content: "建议将目标改为降低柔度。", attachmentIds: [], source: "pi", createdAt: Date.now() });
    render(<ResearchWorkspace researches={[research]} selected={research} command="" busy={false} safeMode={false}
      onCommand={() => undefined} onCreateResearch={() => undefined} onArchive={async () => undefined}
      onRestore={async () => undefined} onDecision={() => undefined} onError={() => undefined}
      onSelect={async () => undefined} onSelectExperiment={() => undefined} setCommand={() => undefined}/>);
    await waitFor(() => expect(apiMocks.conversationMessages).toHaveBeenCalledWith("persisted-chat"));
    await waitFor(() => expect(socket.onmessage).toBeTypeOf("function"));
    await act(async () => socket.onmessage?.({ data: JSON.stringify({ type: "events", events: [{ id: 91, kind: "AGENT_MESSAGE", body: "建议将目标改为降低柔度。", title: "Agent" }] }) } as MessageEvent));
    await waitFor(() => expect(apiMocks.researchSuggestionExtract).toHaveBeenCalledWith(research.id, "event:91", "建议将目标改为降低柔度。"));
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect((screen.getByRole("textbox", { name: "研究目标" }) as HTMLTextAreaElement).value).toBe("降低柔度");
  });

  it("never auto-opens a persisted final result across workspace remounts", async () => {
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
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "科研最终方案详情" })).toBeNull());
    first.unmount();
    render(<ResearchWorkspace {...props}/>);
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "科研最终方案详情" })).toBeNull());
  });
});
