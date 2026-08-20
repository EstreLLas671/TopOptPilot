"""Bounded P1 reviewer workflow executed inside the research's persistent Pi session."""

from __future__ import annotations


REVIEW_TRIGGERS = {"HIGH_FIDELITY_ESCALATION", "HYPOTHESIS_REVISION",
                   "RESEARCH_CONCLUSION", "AMBIGUOUS_FAILURE"}


class ReviewerWorkflow:
    def __init__(self, bridge):
        self.bridge = bridge

    def review(self, research_id: str, trigger: str, proposal_id: str | None = None) -> None:
        if trigger not in REVIEW_TRIGGERS:
            raise ValueError(f"Unsupported reviewer trigger: {trigger}")
        message = (
            f"Act as a bounded Reviewer Sub-Agent for {trigger}. First call research_get_context "
            "and research_get_budget. Audit evidence sufficiency, causal ambiguity, budget value, "
            f"and safety for proposal {proposal_id or 'none'}. Do not submit experiments. Return a "
            "short APPROVE, REVISE, or REJECT recommendation with cited experiment IDs."
        )
        self.bridge.send(research_id, message, "hypothesis-evaluation")
