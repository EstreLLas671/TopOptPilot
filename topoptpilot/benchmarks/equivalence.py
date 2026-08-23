"""MATLAB MCP solver-variant equivalence gate.

The authoritative MATLAB entry points (``topopt_main`` / ``topopt3d_main``) are
the single solver implementation; ``solver_variant`` is a recorded label that
the restricted adapter (``topopt_run_task.m``) attaches per run. This gate
guards the invariant that variant selection never changes solver behaviour: a
``reference_cpu`` run and an ``optimized_cpu`` run on the same controlled task
must produce identical compliance, density and iteration counts, and the same
label must be reproducible run-to-run.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def run_equivalence_gate(worker: Any, *, dimension: int = 2,
                         mesh: str = "coarse") -> dict[str, Any]:
    """Run three controlled solves and compare compliance/density across labels."""
    common = {"load_case": "cantilever", "projection": "heaviside_projection",
              "params": {"volfrac": .4, "penal": 3, "rmin": 1.5, "max_iter": 3,
                         "E": 1.0, "nu": .3}}
    if dimension == 3:
        common["params"].update({"grid3d": [4, 2, 2]})
        mesh = "coarse3d"
        fidelity = "F2"
    else:
        fidelity = "F0"

    def run(variant: str, suffix: str) -> dict[str, Any]:
        task = {**common, "task_id": f"eq-{suffix}", "mesh_level": mesh,
                "fidelity": fidelity, "solver_variant": variant}
        return worker.run(task, "EQUIVALENCE", f"E{suffix}")

    reference = run("reference_cpu", "ref")
    optimized = run("optimized_cpu", "opt")
    reproduced = run("optimized_cpu", "rep")

    compliance_ref = reference["objective"]["compliance"]
    compliance_opt = optimized["objective"]["compliance"]
    compliance_rep = reproduced["objective"]["compliance"]
    density_ref = np.asarray(reference["artifacts"]["density"])
    density_opt = np.asarray(optimized["artifacts"]["density"])
    density_rep = np.asarray(reproduced["artifacts"]["density"])

    relative_error = (abs(compliance_opt - compliance_ref)
                      / max(abs(compliance_ref), 1e-30))
    reproducibility_error = (abs(compliance_rep - compliance_opt)
                             / max(abs(compliance_opt), 1e-30))
    density_identical = (density_ref.shape == density_opt.shape
                         and bool(np.allclose(density_ref, density_opt, atol=0.0, rtol=0.0)))
    iterations_match = (reference["solver"].get("iterations")
                        == optimized["solver"].get("iterations")
                        == reproduced["solver"].get("iterations"))

    passed = (relative_error < 1e-12 and reproducibility_error < 1e-12
              and density_identical and iterations_match)
    return {
        "pass": bool(passed),
        "dimension": dimension,
        "compliance": {"reference_cpu": compliance_ref, "optimized_cpu": compliance_opt,
                       "optimized_cpu_reproduced": compliance_rep},
        "relative_error_reference_vs_optimized": float(relative_error),
        "relative_error_rerun_reproducibility": float(reproducibility_error),
        "density_identical_across_labels": bool(density_identical),
        "iterations_match": bool(iterations_match),
        "matlab_version": reference["solver"].get("matlab_version"),
        "variant_labels": {"reference": reference["solver"].get("solver_variant"),
                           "optimized": optimized["solver"].get("solver_variant")},
    }
