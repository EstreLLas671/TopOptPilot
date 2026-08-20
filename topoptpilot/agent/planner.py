from __future__ import annotations


def build_initial_plan(budget_total: int) -> str:
    coarse_runs = min(3, budget_total)
    return (f"Round 1 Strategy\n\nI will use {coarse_runs} coarse experiments to establish "
            "the effects of projection strength and filter radius before spending the fine-mesh budget.")

