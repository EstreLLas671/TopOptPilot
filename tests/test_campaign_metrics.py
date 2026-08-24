from __future__ import annotations

from topoptpilot.benchmarks.metrics import campaign_metrics


def test_failed_evidence_without_compliance_remains_a_valid_campaign_record() -> None:
    experiments = [
        {
            "id": "E-FAILED",
            "status": "FAILED",
            "fidelity": "F3 — MATLAB 3D Fine",
            "parameters": {"volfrac": 0.4},
            "result": {
                "objective": {},
                "quality": {"gray_ratio": 0.25},
                "error": {"code": "MATLAB_INFRASTRUCTURE"},
            },
        }
    ]

    metrics = campaign_metrics(experiments)

    assert metrics["best_feasible_objective"] is None
    assert metrics["best_compliance"] is None
    assert metrics["best_gray_ratio"] == 0.25
    assert metrics["constraint_violation_rate"] == 1.0
