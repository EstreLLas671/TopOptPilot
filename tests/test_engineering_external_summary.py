from __future__ import annotations

import pytest

from idesktop_v2.artifacts.models import SolverLane
from idesktop_v2.engineering.matlab_runner import MatlabInfrastructureError
from idesktop_v2.engineering.runs import normalize_external_summary


def test_external_summary_preserves_only_measured_metrics() -> None:
    result = normalize_external_summary(
        {
            "status": "completed",
            "objective": 123.5,
            "volume_fraction": 0.4,
            "iterations": 17,
            "objective_history": [150.0, 123.5],
            "provenance": {"resultKind": "solver", "backend": "local-matlab"},
        },
        SolverLane.LOCAL_MATLAB,
    )

    assert result["status"] == "completed"
    assert result["objective"]["compliance"] == 123.5
    assert result["constraints"]["volume_fraction"] == 0.4
    assert result["quality"]["gray_ratio"] is None
    assert result["quality"]["connected_components"] is None
    assert result["quality"]["max_displacement_mm"] is None
    assert result["solver"]["iterations"] == 17
    assert result["solver"]["final_change"] is None
    assert result["solver"]["relative_residual"] is None
    assert "density" not in result["artifacts"]


@pytest.mark.parametrize(
    "summary, message",
    [
        ({"status": "failed", "objective": 1.0, "volume_fraction": 0.4, "iterations": 1}, "completed"),
        ({"status": "completed", "volume_fraction": 0.4, "iterations": 1}, "objective"),
        ({"status": "completed", "objective": 1.0, "iterations": 1}, "volume_fraction"),
        ({"status": "completed", "objective": 1.0, "volume_fraction": 0.4}, "iterations"),
    ],
)
def test_external_summary_rejects_incomplete_solver_evidence(summary, message) -> None:
    with pytest.raises(MatlabInfrastructureError, match=message):
        normalize_external_summary(summary, SolverLane.COMPILED_RUNTIME)
