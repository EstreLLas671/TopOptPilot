def requires_human_approval(mode: str, risk: str, fidelity: str) -> bool:
    del mode, risk
    return str(fidelity).upper().split()[0] == "F3"
