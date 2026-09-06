"""Strict normalization for verified MATLAB and Runtime summaries."""

from __future__ import annotations

import math
from typing import Any

from topoptpilot_desktop.artifacts.models import SolverLane
from topoptpilot_desktop.engineering.matlab_runner import MatlabInfrastructureError


def _number(
    summary: dict[str, Any],
    names: tuple[str, ...],
    label: str,
    *,
    required: bool,
) -> float | None:
    value: Any = None
    for name in names:
        if name in summary:
            value = summary[name]
            break
    if isinstance(value, dict):
        value = value.get("compliance")
    if value is None:
        if required:
            raise MatlabInfrastructureError(f"external solver summary is missing {label}")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MatlabInfrastructureError(f"external solver summary has invalid {label}") from exc
    if not math.isfinite(number):
        raise MatlabInfrastructureError(f"external solver summary has non-finite {label}")
    return number


def normalize_external_summary(
    summary: dict[str, Any],
    lane: SolverLane,
) -> dict[str, Any]:
    if summary.get("status") != "completed":
        raise MatlabInfrastructureError("external solver summary is not completed")
    compliance = _number(summary, ("objective", "compliance"), "objective", required=True)
    volume_fraction = _number(
        summary,
        ("volume_fraction", "volumeFraction"),
        "volume_fraction",
        required=True,
    )
    iterations_value = _number(summary, ("iterations",), "iterations", required=True)
    iterations = int(iterations_value)
    if iterations < 1 or iterations != iterations_value:
        raise MatlabInfrastructureError("external solver summary has invalid iterations")

    history_values = summary.get("objective_history") or []
    if not isinstance(history_values, list):
        raise MatlabInfrastructureError("external solver summary has invalid objective_history")
    history = []
    for index, value in enumerate(history_values):
        try:
            measured = float(value)
        except (TypeError, ValueError) as exc:
            raise MatlabInfrastructureError(
                "external solver summary has invalid objective_history"
            ) from exc
        if not math.isfinite(measured):
            raise MatlabInfrastructureError(
                "external solver summary has non-finite objective_history"
            )
        history.append({"iteration": index + 1, "compliance": measured})

    provenance = summary.get("provenance")
    if (
        not isinstance(provenance, dict)
        or provenance.get("resultKind") != "solver"
        or provenance.get("backend") != lane.value
    ):
        raise MatlabInfrastructureError("external solver summary has invalid provenance")

    return {
        "status": "completed",
        "objective": {"compliance": compliance},
        "constraints": {"volume_fraction": volume_fraction},
        "quality": {
            "gray_ratio": _number(
                summary, ("gray_ratio",), "gray_ratio", required=False
            ),
            "connected_components": _number(
                summary,
                ("connected_components",),
                "connected_components",
                required=False,
            ),
            "max_displacement_mm": _number(
                summary,
                ("max_displacement_mm",),
                "max_displacement_mm",
                required=False,
            ),
        },
        "solver": {
            "backend": lane.value,
            "iterations": iterations,
            "final_change": _number(
                summary, ("final_change",), "final_change", required=False
            ),
            "relative_residual": _number(
                summary,
                ("relative_residual",),
                "relative_residual",
                required=False,
            ),
        },
        "artifacts": {"history": history},
        "provenance": provenance,
    }
