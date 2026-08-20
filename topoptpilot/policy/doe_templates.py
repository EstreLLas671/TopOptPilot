"""Small, explicit DOE templates used by planners and demos."""


def coarse_beta_sweep(volfrac: float = 0.4) -> list[dict]:
    return [
        {"purpose": f"Coarse beta={beta} screening", "fidelity": "F0 — 2D Coarse",
         "mesh_level": "coarse", "parameters": {
             "volfrac": volfrac, "rmin": 1.5, "penal": 3, "beta": beta, "max_iter": 60,
         }}
        for beta in (1, 4, 8)
    ]


def discriminating_experiments(template: str, control: dict) -> list[dict]:
    """Return control-variable branches; the unchanged control is already observed."""
    if template == "beta_vs_rmin":
        return [
            {"purpose": "Test whether excessive beta caused disconnection",
             "parameters": {**control, "beta": max(1.0, float(control.get("beta", 16)) / 2)},
             "controlled_factors": ["beta"]},
            {"purpose": "Test whether insufficient rmin caused disconnection",
             "parameters": {**control, "rmin": min(4.0, float(control.get("rmin", 1.5)) + 0.5)},
             "controlled_factors": ["rmin"]},
        ]
    if template == "beta_vs_penal":
        return [
            {"purpose": "Test beta explanation for grayness",
             "parameters": {**control, "beta": min(16.0, float(control.get("beta", 4)) * 2)},
             "controlled_factors": ["beta"]},
            {"purpose": "Test penal explanation for grayness",
             "parameters": {**control, "penal": min(5.0, float(control.get("penal", 3)) + 1)},
             "controlled_factors": ["penal"]},
        ]
    if template == "projection_vs_controller":
        return [
            {"purpose": "Test projection explanation for oscillation",
             "parameters": {**control, "beta": max(1.0, float(control.get("beta", 8)) / 2)},
             "controlled_factors": ["projection"]},
            {"purpose": "Test controller explanation for oscillation",
             "parameters": {**control, "controller": "joint_feedback_controller"},
             "controlled_factors": ["controller"]},
        ]
    raise ValueError(f"Unknown DOE template: {template}")
