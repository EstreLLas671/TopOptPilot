from __future__ import annotations

import numpy as np

from solver.continuation import PeriodicController
from solver.result_schema import build_result
from solver.topopt_engine import run_topopt


def test_periodic_controller_starts_at_requested_beta() -> None:
    controller = PeriodicController({"beta": 3.0, "beta_max": 16.0, "beta_interval": 10})
    assert controller.beta(1) == 3.0
    assert controller.beta(10) == 3.0
    assert controller.beta(11) == 6.0
    assert controller.beta(31) == 16.0


def test_max_iteration_is_not_falsely_reported_as_converged() -> None:
    result = build_result(
        task_spec={"params": {}}, status="max_iter", compliance=1.0,
        xPhys=np.full((2, 2), 0.4), U=np.zeros(18), history=[], iterations=2,
        final_change=0.2, relative_residual=0.0, solve_time=0.01,
    )
    assert result["status"] == "max_iter"
    assert result["solver"]["converged"] is False


def test_desktop_matlab_sources_accept_projection_controls() -> None:
    from pathlib import Path

    sources = [
        Path("matlab/engineering/TopOpt_2D/topopt_main.m"),
        Path("matlab/engineering/TopOpt-3D/topopt3d_main.m"),
    ]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert "heaviside_projection" in text
        assert "scheduled_beta" in text


def test_projected_cantilever_reaches_low_grayness_without_full_move_oscillation() -> None:
    result = run_topopt({
        "load_case": "cantilever",
        "mesh_level": "coarse",
        "geometry": {"nelx": 24, "nely": 8},
        "projection": "heaviside_projection",
        "controller": "periodic_controller",
        "filter": "density_filter",
        "params": {
            "volfrac": 0.4, "penal": 3.0, "rmin": 2.0,
            "beta": 3.0, "beta_max": 16.0, "move": 0.2,
            "max_iter": 80, "min_iter": 10,
        },
    })
    assert result["solver"]["beta_final"] == 16.0
    assert result["quality"]["gray_ratio"] <= 0.35
    assert result["solver"]["final_change"] <= 0.05 + 1e-12
