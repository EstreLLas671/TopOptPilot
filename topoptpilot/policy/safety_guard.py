"""Deterministic, inspectable safety policy for experiment proposals."""

from __future__ import annotations

from typing import Any


def evaluate_safety(parameters: dict[str, Any], fidelity: str = "") -> dict[str, str | bool]:
    beta = float(parameters.get("beta", parameters.get("beta_max", 1)))
    rmin = float(parameters.get("rmin", 1.5))
    max_iter = int(parameters.get("max_iter", 80))
    risk = "LOW"
    reasons: list[str] = []
    requires_approval = False
    violations: list[str] = []
    volfrac = float(parameters.get("volfrac", 0.4))
    penal = float(parameters.get("penal", 3.0))
    if not 0.1 <= volfrac <= 0.8:
        violations.append("volfrac must be within [0.1, 0.8]")
    if not 0.75 <= rmin <= 4.0:
        violations.append("rmin must be within [0.75, 4.0]")
    if not 1.0 <= beta <= 32.0:
        violations.append("beta must be within [1, 32]")
    if not 1.0 <= penal <= 5.0:
        violations.append("penal must be within [1, 5]")
    if not 1 <= max_iter <= 500:
        violations.append("max_iter must be within [1, 500]")
    if beta >= 16 and rmin < 2.0:
        risk = "MEDIUM"
        reasons.append("High beta with a narrow filter radius can increase disconnection risk.")
    if "F3" in fidelity.upper() or "MATLAB" in fidelity.upper():
        risk = "HIGH"
        requires_approval = True
        reasons.append("MATLAB high-fidelity execution consumes protected compute budget.")
    elif "F2" in fidelity.upper() or "3D" in fidelity.upper() or max_iter > 250:
        risk = "MEDIUM"
        reasons.append("3D or long execution consumes protected compute budget.")
    return {
        "risk": risk,
        "safe": not violations,
        "requires_approval": requires_approval,
        "reason": " ".join([*violations, *reasons]) or "Parameters are inside the configured operating envelope.",
    }
