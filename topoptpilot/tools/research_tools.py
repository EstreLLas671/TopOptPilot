"""The complete allowlisted scientific tool surface exposed to Pi."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
}


class ResearchTools:
    def __init__(self, service: "ResearchService"):
        self.service = service
        self.memory = ResearchMemory()
        self.compiler = IntentCompiler()

    def invoke(self, research_id: str, name: str, arguments: dict[str, Any]) -> Any:
        if name not in ALLOWED_TOOLS:
            raise PermissionError(f"Tool {name} is not allowed")
        method = getattr(self, name)
        self.service.store.append_event(research_id, "TOOL_CALL", name,
                                        f"Arguments: {arguments}", payload={"arguments": arguments})
        try:
            result = method(research_id, **arguments)
        except Exception as exc:
            title = "INVALID INTENT" if name == "policy_compile_intent" else name
            self.service.store.append_event(research_id, "TOOL_RESULT", title,
                                            f"Tool rejected request: {exc}",
                                            payload={"error": str(exc)})
            raise
        self.service.store.append_event(research_id, "TOOL_RESULT", name, "Tool completed.",
                                        payload={"result": _compact(result)})
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
        request = IntentRequest.model_validate(arguments)
        proposals = self.compiler.compile(research, self.service.store.list_experiments(research_id), request)
        saved = []
        for proposal in proposals:
            data = proposal.model_dump(mode="json")
            saved.append(self.service.store.create_proposal({**data, "status": "PREVIEW"}))
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
            return {"status": item["status"], "result": None}
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
        return {"a": a, "b": b, "delta": {
            "compliance": _delta(lm.get("compliance"), rm.get("compliance")),
            "gray_ratio": _delta(lm.get("gray_ratio"), rm.get("gray_ratio")),
            "connected_components": _delta(lm.get("connected_components"), rm.get("connected_components")),
        }, "parameter_differences": changed, "controlled_comparison": len(changed) == 1}

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
