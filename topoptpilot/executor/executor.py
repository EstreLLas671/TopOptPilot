"""Task conversion facade kept separate from the queue transport."""


def build_solver_task(experiment: dict, research: dict | None = None) -> dict:
    research = research or {}
    parameters = dict(experiment["parameters"])
    material = dict(research.get("material") or {})
    unit_context = _unit_context(research)
    if unit_context["trusted"] and material.get("E_MPa") is not None:
        material["E"] = float(material["E_MPa"])
    beta = float(parameters.get("beta", parameters.get("beta_max", 1)))
    projected = beta > 1
    projection = str(parameters.get("projection", "heaviside_projection" if projected else "none"))
    controller = str(parameters.get("controller", "periodic_controller" if projection != "none" else "fixed_controller"))
    filter_name = str(parameters.get("filter", "density_filter" if projection != "none" else "sensitivity_filter"))
    return {
        "task_id": experiment["id"], "experiment_group": experiment["id"],
        "fidelity": str(experiment.get("fidelity", "F0")).split()[0],
        "solver_variant": experiment.get("solver_variant", "auto"),
        "acceleration_mode": experiment.get("acceleration_mode", "auto"),
        "hypothesis_id": research.get("hypothesis") or "workspace",
        "load_case": _load_case(research),
        "mesh_level": experiment["mesh_level"],
        "projection": projection,
        "controller": controller,
        "filter": filter_name,
        "geometry": research.get("geometry"),
        "bc_config": {**(research.get("boundary_conditions") or {}),
                      "load_scale": _load_scale(research)},
        "unit_context": unit_context,
        "work_package": {"material": material,
                         "volume_fraction": research.get("constraints", {}).get(
                             "volume_fraction", parameters.get("volfrac", .4))},
        "params": {**parameters, **material, "beta_max": max(beta, 2)},
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


def _unit_context(research: dict) -> dict:
    """Only assert MPa when the complete N-mm-MPa chain is explicit."""
    geometry = research.get("geometry") or {}
    material = research.get("material") or {}
    loads = research.get("loads") or []
    load = loads[0] if loads else {}
    length_unit = str(geometry.get("unit") or geometry.get("length_unit") or "").strip().lower()
    load_unit = str(load.get("unit") or load.get("force_unit") or "").strip().lower()
    modulus_unit = str(material.get("E_unit") or material.get("youngs_modulus_unit") or "").strip().lower()
    cell_size = geometry.get("cell_size_mm")
    explicit_modulus = material.get("E_MPa") is not None or modulus_unit == "mpa"
    trusted = (
        length_unit in {"mm", "millimeter", "millimetre"}
        and load_unit in {"n", "newton", "newtons"}
        and explicit_modulus
        and isinstance(cell_size, (int, float)) and abs(float(cell_size) - 1.0) <= 1e-12
    )
    return {
        "trusted": trusted,
        "stress_unit": "MPa" if trusted else "normalized",
        "length_unit": length_unit or None,
        "force_unit": load_unit or None,
        "modulus_unit": "MPa" if explicit_modulus else (modulus_unit or None),
        "cell_size_mm": float(cell_size) if isinstance(cell_size, (int, float)) else None,
        "reason": (
            "载荷单位 N、几何单位 mm、材料模量 MPa 与 1 mm 单元尺度均已明确"
            if trusted else "当前单位单元求解器仅在 N、mm、MPa 与 cell_size_mm=1 的完整链路下按 MPa 校核"
        ),
    }
