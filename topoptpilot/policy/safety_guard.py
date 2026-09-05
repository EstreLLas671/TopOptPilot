"""Deterministic, inspectable safety policy for experiment proposals."""

from __future__ import annotations

from typing import Any
from topoptpilot.nomenclature import normalize_stage


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
    projection = str(parameters.get("projection", "heaviside_projection" if beta > 1 else "none"))
    controller = str(parameters.get("controller", "periodic_controller" if beta > 1 else "fixed_controller"))
    filter_name = str(parameters.get("filter", "density_filter" if beta > 1 else "sensitivity_filter"))
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
    if projection not in {"none", "heaviside_projection"}:
        violations.append("projection is not allowlisted")
    if controller not in {"fixed_controller", "periodic_controller"}:
        violations.append("controller is not allowlisted")
    if filter_name not in {"sensitivity_filter", "density_filter"}:
        violations.append("filter is not allowlisted")
    if beta >= 16 and rmin < 2.0:
        risk = "MEDIUM"
        reasons.append("High beta with a narrow filter radius can increase disconnection risk.")
    fidelity_code = normalize_stage(fidelity) if fidelity else ""
    if fidelity_code == "STEP4":
        risk = "HIGH"
        reasons.append("MATLAB 真实网络执行需要较长时间；完成后必须人工审阅结果。")
    elif fidelity_code == "STEP3" or max_iter > 250:
        risk = "MEDIUM"
        reasons.append("3D 或长迭代执行需要较长时间。")
    return {
        "risk": risk,
        "safe": not violations,
        "requires_approval": requires_approval,
        "reason": " ".join([*violations, *reasons]) or "Parameters are inside the configured operating envelope.",
    }
