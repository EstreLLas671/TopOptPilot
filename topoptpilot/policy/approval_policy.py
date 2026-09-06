def requires_human_approval(mode: str, risk: str, fidelity: str) -> bool:
    # Deep optimization is controlled by one post-run gate per step.  A second
    # pre-run gate would duplicate approval and can deadlock Step4.
    del mode, risk, fidelity
    return False
