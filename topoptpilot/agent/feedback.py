from __future__ import annotations


def build_feedback(evaluation: dict) -> str:
    return f"{evaluation['next_action']}\n\nReason: {evaluation['summary']}"

