"""Task conversion facade kept separate from the queue transport."""


def build_solver_task(experiment: dict, research: dict | None = None) -> dict:
    research = research or {}
    parameters = dict(experiment["parameters"])
    beta = float(parameters.get("beta", parameters.get("beta_max", 1)))
    projected = beta > 1
    projection = str(parameters.get("projection", "heaviside_projection" if projected else "none"))
    controller = str(parameters.get("controller", "periodic_controller" if projection != "none" else "fixed_controller"))
    filter_name = str(parameters.get("filter", "density_filter" if projection != "none" else "sensitivity_filter"))
    return {
        "task_id": experiment["id"], "experiment_group": experiment["id"],
        "hypothesis_id": research.get("hypothesis") or "workspace",
        "load_case": _load_case(research),
        "mesh_level": experiment["mesh_level"],
        "projection": projection,
        "controller": controller,
        "filter": filter_name,
        "geometry": research.get("geometry"),
        "bc_config": {**(research.get("boundary_conditions") or {}),
                      "load_scale": _load_scale(research)},
        "work_package": {"material": research.get("material", {}),
                         "volume_fraction": research.get("constraints", {}).get(
                             "volume_fraction", parameters.get("volfrac", .4))},
        "params": {**parameters, **research.get("material", {}), "beta_max": max(beta, 2)},
    }


def _load_case(research: dict) -> str:
    boundary = str((research.get("boundary_conditions") or {}).get("type", "")).strip()
    if boundary:
        return boundary
    loads = research.get("loads") or []
    return str((loads[0] if loads else {}).get("type", "vertical"))


def _load_scale(research: dict) -> float:
    loads = research.get("loads") or []
    return float((loads[0] if loads else {}).get("magnitude", 1.0))
