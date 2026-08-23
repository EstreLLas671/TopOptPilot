"""The complete allowlisted scientific tool surface exposed to Pi."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
import threading

from topoptpilot.fidelity import FidelityManager
from topoptpilot.memory import ResearchMemory
from topoptpilot.memory.retriever import retrieve_events
from topoptpilot.policy.intent_compiler import IntentCompiler
from topoptpilot.schemas import IntentRequest

if TYPE_CHECKING:
    from topoptpilot.service.research_service import ResearchService


ALLOWED_TOOLS = {
    "research_get_context", "research_query_history", "research_get_budget",
    "policy_compile_intent", "experiment_preview", "experiment_submit",
    "experiment_status", "experiment_result", "experiment_compare",
    "research_get_pareto", "failure_get_evidence",
    "knowledge_search", "knowledge_get", "solver_get_capabilities",
    "subagent_dispatch", "subagent_status",
}


class ResearchTools:
    def __init__(self, service: "ResearchService"):
        self.service = service
        self.memory = ResearchMemory()
        self.compiler = IntentCompiler()
        self._invocation = threading.local()

    def invoke(self, research_id: str, name: str, arguments: dict[str, Any],
               *, source: str = "API", role: str = "RESEARCH_LEAD") -> Any:
        if name not in ALLOWED_TOOLS:
            raise PermissionError(f"Tool {name} is not allowed")
        if role != "RESEARCH_LEAD":
            from topoptpilot.agent_runtime.subagents import allowed_tools_for_role
            if name not in allowed_tools_for_role(role):
                raise PermissionError(f"Role {role} cannot use tool {name}")
        method = getattr(self, name)
        self.service.store.append_event(research_id, "TOOL_CALL", name,
                                        f"Arguments: {arguments}", payload={"arguments": arguments},
                                        source=source, event_type="AGENT_TOOL_CALL")
        previous = getattr(self._invocation, "source", None)
        self._invocation.source = source
        try:
            result = method(research_id, **arguments)
        except Exception as exc:
            title = "INVALID INTENT" if name == "policy_compile_intent" else name
            self.service.store.append_event(research_id, "TOOL_RESULT", title,
                                            f"Tool rejected request: {exc}",
                                            payload={"error": str(exc)}, source=source,
                                            event_type="AGENT_TOOL_CALL")
            raise
        finally:
            self._invocation.source = previous
        self.service.store.append_event(research_id, "TOOL_RESULT", name, "Tool completed.",
                                        payload={"result": _compact(result)}, source=source,
                                        event_type="AGENT_TOOL_CALL")
        return result

    def research_get_context(self, research_id: str) -> dict:
        research = self.service._require_research(research_id)
        memory = self.memory.build(research, self.service.store.list_experiments(research_id),
                                   self.service.store.list_events(research_id),
                                   self.service.store.list_decisions(research_id))
        for level in ("L1", "L2", "L3"):
            self.service.store.save_memory_snapshot(research_id, level, memory[level])
        return memory["L3"]

    def research_query_history(self, research_id: str, query: str, limit: int = 8) -> list[dict]:
        events = retrieve_events(self.service.store.list_events(research_id), query, min(limit, 20))
        experiment_ids = {event.get("experiment_id") for event in events if event.get("experiment_id")}
        experiments = [item for item in self.service.store.list_experiments(research_id)
                       if item["id"] in experiment_ids]
        return [{"event": event} for event in events] + [{"experiment": _compact(item)} for item in experiments]

    def research_get_budget(self, research_id: str) -> dict:
        return FidelityManager.budget(self.service._require_research(research_id),
                                      self.service.store.list_experiments(research_id))

    def policy_compile_intent(self, research_id: str, **arguments) -> list[dict]:
        research = self.service._require_research(research_id)
        source = arguments.pop("_decision_source", None) or getattr(self._invocation, "source", None) or "HUMAN"
        request = IntentRequest.model_validate(arguments)
        proposals = self.compiler.compile(research, self.service.store.list_experiments(research_id), request)
        saved = []
        session = self.service.store.get_agent_session(research_id) or {}
        evidence_ids = [item["id"] for item in self.service.store.list_experiments(research_id)
                        if item.get("result")][-6:]
        for proposal in proposals:
            data = proposal.model_dump(mode="json")
            saved.append(self.service.store.create_proposal({**data, "status": "PREVIEW",
                "decision_source": source, "intent_source": source,
                "policy_version": "v6-intent-compiler-1",
                "model": self.service.pi_runtime.model if source == "PI_AGENT" and self.service.pi_runtime else None,
                "provider": "dashscope" if source == "PI_AGENT" else None,
                "session_id": session.get("session_id"), "evidence_ids": evidence_ids}))
        return saved

    def experiment_preview(self, research_id: str, proposal_id: str) -> dict:
        proposal = self._proposal(research_id, proposal_id)
        budget = self.research_get_budget(research_id)
        code = proposal["fidelity"]
        return {**proposal, "budget_remaining": budget["remaining"].get(code, 0),
                "can_submit": proposal["safety_status"] != "REJECTED"
                and budget["remaining"].get(code, 0) > 0}

    def experiment_submit(self, research_id: str, proposal_id: str) -> dict:
        return self.service.submit_proposal(research_id, proposal_id)

    def experiment_status(self, research_id: str, experiment_id: str) -> dict:
        item = self.service.get_experiment(experiment_id)
        self._same_research(research_id, item)
        return {key: item.get(key) for key in
                ("id", "status", "progress", "current_iteration", "run_id", "error")}

    def experiment_result(self, research_id: str, experiment_id: str) -> dict:
        item = self.service.get_experiment(experiment_id)
        self._same_research(research_id, item)
        if not item.get("result"):
            return {"status": item["status"], "compliance": None, "gray_ratio": None,
                    "connected_components": None, "volume_fraction": None,
                    "volume_error": None, "iterations": item.get("current_iteration", 0),
                    "fidelity": item["fidelity"], "solver": None}
        result = item["result"]
        objective, constraints, quality, solver = (result.get(name, {}) for name in
                                                    ("objective", "constraints", "quality", "solver"))
        target = self.service._require_research(research_id)["constraints"].get("volume_fraction")
        actual = constraints.get("volume_fraction")
        volume_error = None if target is None or actual is None else float(actual) - float(target)
        return {"status": item["status"], "compliance": objective.get("compliance"),
                "gray_ratio": quality.get("gray_ratio"),
                "connected_components": quality.get("connected_components"),
                "volume_fraction": actual, "volume_error": volume_error,
                "iterations": solver.get("iterations"), "fidelity": item["fidelity"],
                "solver": {key: value for key, value in solver.items() if key != "raw_output"}}

    def experiment_compare(self, research_id: str, a: str, b: str) -> dict:
        left, right = (self.service.get_experiment(value) for value in (a, b))
        self._same_research(research_id, left)
        self._same_research(research_id, right)
        lm, rm = _metrics(left), _metrics(right)
        keys = set(left["parameters"]) | set(right["parameters"])
        changed = {key: {"a": left["parameters"].get(key), "b": right["parameters"].get(key)}
                   for key in keys if left["parameters"].get(key) != right["parameters"].get(key)}
        result = {"a": a, "b": b, "delta": {
            "compliance": _delta(lm.get("compliance"), rm.get("compliance")),
            "gray_ratio": _delta(lm.get("gray_ratio"), rm.get("gray_ratio")),
            "connected_components": _delta(lm.get("connected_components"), rm.get("connected_components")),
        }, "parameter_differences": changed, "controlled_comparison": len(changed) == 1}
        self.service.store.append_event(
            research_id, "COMPARISON", "CONTROLLED COMPARISON",
            ("Exactly one solver parameter differs." if result["controlled_comparison"] else
             "Comparison is descriptive only because multiple or zero solver parameters differ."),
            payload=result, source="EVALUATOR", event_type="COMPARISON_RESULT")
        return result

    def research_get_pareto(self, research_id: str) -> list[dict]:
        research = self.service._require_research(research_id)
        memory = self.memory.build(research, self.service.store.list_experiments(research_id),
                                   self.service.store.list_events(research_id),
                                   self.service.store.list_decisions(research_id))
        return memory["L2"]["pareto_candidates"]

    def failure_get_evidence(self, research_id: str, failure_type: str) -> list[dict]:
        context = self.research_get_context(research_id)
        failures = [item for item in context["known_failures"] if item["type"] == failure_type]
        experiments = {item["id"]: item for item in self.service.store.list_experiments(research_id)}
        return [{**failure, "parameters": experiments.get(failure["experiment_id"], {}).get("parameters", {})}
                for failure in failures]

    def knowledge_search(self, research_id: str, query: str, limit: int = 8,
                         category: str | None = None) -> list[dict]:
        research = self.service._require_research(research_id)
        results = self.service.knowledge.search(query, research.get("locale", "zh-CN"), category, limit)
        self.service.store.append_event(
            research_id, "KNOWLEDGE", "KNOWLEDGE REFERENCED",
            f"Retrieved {len(results)} offline knowledge entries for: {query}",
            payload={"query": query, "knowledge_ids": [item["id"] for item in results]},
            source="KNOWLEDGE_BASE", event_type="KNOWLEDGE_REFERENCED")
        return results

    def knowledge_get(self, research_id: str, document_id: str) -> dict:
        research = self.service._require_research(research_id)
        value = self.service.knowledge.get(document_id, research.get("locale", "zh-CN"))
        self.service.store.append_event(
            research_id, "KNOWLEDGE", "KNOWLEDGE REFERENCED", value["citation"],
            payload={"knowledge_ids": [document_id]}, source="KNOWLEDGE_BASE",
            event_type="KNOWLEDGE_REFERENCED")
        return value

    def solver_get_capabilities(self, research_id: str) -> dict:
        self.service._require_research(research_id)
        capabilities = self.service.solver_capabilities()
        self.service.store.append_event(
            research_id, "SOLVER", "SOLVER CAPABILITY", "Solver capabilities were inspected.",
            payload=capabilities, source="MATLAB_MCP", event_type="SOLVER_CAPABILITY")
        return capabilities

    def subagent_dispatch(self, research_id: str, role: str, objective: str,
                          evidence_ids: list[str] | None = None,
                          proposal_id: str | None = None) -> dict:
        if not self.service.pi_runtime:
            raise RuntimeError("Pi runtime is unavailable")
        return self.service.pi_runtime.subagents.dispatch(
            research_id, role, objective, evidence_ids, proposal_id)

    def subagent_status(self, research_id: str, task_id: str | None = None):
        if not self.service.pi_runtime:
            return self.service.store.get_subagent_task(task_id) if task_id else \
                self.service.store.list_subagent_tasks(research_id)
        return self.service.pi_runtime.subagents.status(research_id, task_id)

    def _proposal(self, research_id: str, proposal_id: str) -> dict:
        proposal = self.service.store.get_proposal(proposal_id)
        if not proposal or proposal["research_id"] != research_id:
            raise KeyError(f"Proposal {proposal_id} does not exist")
        return proposal

    @staticmethod
    def _same_research(research_id: str, experiment: dict) -> None:
        if experiment["research_id"] != research_id:
            raise PermissionError("Experiment belongs to another research")


def _metrics(experiment: dict) -> dict:
    result = experiment.get("result") or {}
    return {**result.get("objective", {}), **result.get("quality", {})}


def _delta(a, b):
    return None if a is None or b is None else b - a


def _compact(value):
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items()
                if key not in {"density", "history", "artifacts"}}
    if isinstance(value, list):
        return [_compact(item) for item in value[:20]]
    return value
