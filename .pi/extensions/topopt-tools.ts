import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const TOOL_NAMES = new Set([
  "research_get_context", "research_query_history", "research_get_budget",
  "policy_compile_intent", "experiment_preview", "experiment_submit",
  "experiment_status", "experiment_result", "experiment_compare",
  "research_get_pareto", "failure_get_evidence",
]);

async function invoke(tool: string, args: unknown, signal: AbortSignal) {
  const baseUrl = process.env.TOPPILOT_TOOL_URL;
  const researchId = process.env.TOPPILOT_RESEARCH_ID;
  const token = process.env.TOPPILOT_TOOL_TOKEN;
  if (!baseUrl || !researchId || !token) throw new Error("TopOptPilot tool gateway is not configured");
  const response = await fetch(`${baseUrl}/tool`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-topopt-token": token },
    body: JSON.stringify({ research_id: researchId, tool, arguments: args }),
    signal,
  });
  const data = await response.json();
  if (!response.ok || !data.ok) throw new Error(data.error || `Tool gateway returned ${response.status}`);
  return data.result;
}

function register(pi: ExtensionAPI, name: string, description: string, parameters: any) {
  pi.registerTool({
    name,
    label: name,
    description,
    parameters,
    async execute(_toolCallId, params, signal) {
      const result = await invoke(name, params, signal);
      return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
    },
  });
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event) => {
    if (!TOOL_NAMES.has(event.toolName)) {
      return { block: true, reason: `Tool ${event.toolName} is outside the research sandbox` };
    }
  });

  register(pi, "research_get_context", "Read compact authoritative L3 research context before planning.", Type.Object({}));
  register(pi, "research_query_history", "Retrieve relevant historical experiments and evidence.", Type.Object({ query: Type.String(), limit: Type.Optional(Type.Number()) }));
  register(pi, "research_get_budget", "Read remaining total and per-fidelity budgets.", Type.Object({}));
  register(pi, "policy_compile_intent", "Compile scientific intent into safe controlled experiment proposals.", Type.Object({
    intent: Type.String(), preserve: Type.Optional(Type.Array(Type.String())),
    explanations: Type.Optional(Type.Array(Type.String())), factors: Type.Optional(Type.Array(Type.String())),
    factor: Type.Optional(Type.String()), source_experiment: Type.Optional(Type.String()),
  }));
  register(pi, "experiment_preview", "Preview cost, risk, purpose, and approval requirement without running FEM.", Type.Object({ proposal_id: Type.String() }));
  register(pi, "experiment_submit", "Submit an already compiled safe proposal asynchronously.", Type.Object({ proposal_id: Type.String() }));
  register(pi, "experiment_status", "Read asynchronous experiment status and progress.", Type.Object({ experiment_id: Type.String() }));
  register(pi, "experiment_result", "Read structured final metrics for a completed experiment.", Type.Object({ experiment_id: Type.String() }));
  register(pi, "experiment_compare", "Compute deterministic metric and parameter differences.", Type.Object({ a: Type.String(), b: Type.String() }));
  register(pi, "research_get_pareto", "Read compliance-versus-gray Pareto candidates.", Type.Object({}));
  register(pi, "failure_get_evidence", "Retrieve experiments supporting a structured failure type.", Type.Object({ failure_type: Type.String() }));
}
