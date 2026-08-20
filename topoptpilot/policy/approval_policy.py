def requires_human_approval(mode: str, risk: str, fidelity: str) -> bool:
    return mode.upper() == "COPILOT" or risk.upper() == "HIGH" or "3D" in fidelity.upper()

