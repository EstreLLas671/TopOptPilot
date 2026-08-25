// @vitest-environment jsdom

import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  researchArtifacts: vi.fn(),
  stream: vi.fn(),
}));

vi.mock("../../api", () => ({ api: apiMocks }));

import type { Research } from "../../types";
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
    view.unmount();
    expect(socket.close).toHaveBeenCalledTimes(1);
  });
});
