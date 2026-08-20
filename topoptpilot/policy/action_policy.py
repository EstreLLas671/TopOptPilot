"""Map objective evaluation to a bounded next research action."""


ALLOWED_ACTIONS = {
    "PROMOTE_OR_REPORT", "RESTORE_CONNECTIVITY", "REDUCE_GRAYNESS", "RETRY_OR_REVISE",
}


def choose_action(evaluation: dict) -> str:
    action = evaluation.get("next_action", "RETRY_OR_REVISE")
    return action if action in ALLOWED_ACTIONS else "RETRY_OR_REVISE"

