"""Task conversion facade kept separate from the queue transport."""
from topoptpilot.nomenclature import normalize_stage


_VISIBLE_PARAMETER_MAP = {
    "penal": "penal",
    "rmin": "rmin",
    "max_iter": "maxIterations",
    "min_iter": "minIterations",
    "filter_strategy": "filterStrategy",
    "accuracy": "accuracy",
}


def _scaled_grid(config: dict, fidelity: str) -> tuple[int, int, int]:
    fidelity = normalize_stage(fidelity)
    factor = {"STEP1": 0.5, "STEP2": 0.75, "STEP3": 0.5, "STEP4": 1.0}.get(fidelity, 1.0)
    values = [
        max(1, int(round(float(config.get(name, fallback)) * factor)))
        for name, fallback in (("nelx", 24), ("nely", 8), ("nelz", 6))
    ]
    if fidelity in {"STEP1", "STEP2"}:
        values[2] = 1
    return values[0], values[1], values[2]


def build_solver_task(experiment: dict, research: dict | None = None) -> dict:
    research = research or {}
    parameters = dict(experiment["parameters"])
    configured = dict(((research.get("defaults") or {}).get("optimization_config") or {}))
    fidelity_code = normalize_stage(experiment.get("fidelity"))
    if configured:
        for target, source in _VISIBLE_PARAMETER_MAP.items():
            if source in configured:
                parameters[target] = configured[source]
        parameters["volfrac"] = float(parameters.get("volfrac", configured.get("volfrac", 0.4)))
    material = dict(research.get("material") or {})
    configured_material = dict(configured.get("material") or {})
    if configured_material:
        material.update({
            "preset": configured_material.get("preset"),
            "name": configured_material.get("name"),
            "E": float(configured_material.get("youngsModulusGPa", 1.0)),
            "E_GPa": float(configured_material.get("youngsModulusGPa", 1.0)),
            "nu": float(configured_material.get("poissonRatio", 0.3)),
            "density_kg_m3": float(configured_material.get("densityKgM3", 1.0)),
            "yield_strength_MPa": float(configured_material.get("yieldStrengthMPa", 1.0)),
        })
    elif material.get("E_GPa") is not None:
        material["E"] = float(material["E_GPa"])
    unit_context = _unit_context(research)
    if unit_context["trusted"] and material.get("E_MPa") is not None:
        material["E"] = float(material["E_MPa"])
    beta = float(parameters.get("beta", parameters.get("beta_max", 1)))
    beta_max = float(parameters.get("beta_max", max(beta, 32.0 if beta > 1 else 2.0)))
    projected = beta > 1
    projection = str(parameters.get("projection", "heaviside_projection" if projected else "none"))
    controller = str(parameters.get("controller", "periodic_controller" if projection != "none" else "fixed_controller"))
    filter_name = str(parameters.get("filter", "density_filter" if projection != "none" else "sensitivity_filter"))
    geometry = dict(research.get("geometry") or {})
    if configured:
        geometry.update({
            "dimension": "2d" if fidelity_code in {"STEP1", "STEP2"} else "3d",
            "dimensions": list(configured.get("dimensions") or geometry.get("dimensions") or []),
            "unit": configured.get("unit", geometry.get("unit")),
            "cell_size_m": configured.get("cellSizeMeters", geometry.get("cell_size_m")),
            "accuracy": configured.get("accuracy", geometry.get("accuracy")),
        })
        nelx, nely, nelz = _scaled_grid(configured, fidelity_code)
        geometry.update({"nelx": nelx, "nely": nely, "nelz": nelz})
        if fidelity_code in {"STEP1", "STEP2"}:
            parameters.update({"nelx": nelx, "nely": nely})
            parameters.pop("grid3d", None)
        else:
            parameters["grid3d"] = [nelx, nely, nelz]
    elif fidelity_code in {"STEP3", "STEP4"}:
        candidate = [geometry.get("nelx"), geometry.get("nely"), geometry.get("nelz")]
        if all(isinstance(value, (int, float)) and int(value) > 0 for value in candidate):
            parameters["grid3d"] = [int(value) for value in candidate]
    load_case = str(configured.get("bcType") or _load_case(research))
    boundary = {**(research.get("boundary_conditions") or {}), "type": load_case}
    return {
        "task_id": experiment["id"], "experiment_group": experiment["id"],
        "fidelity": fidelity_code,
        "solver_variant": experiment.get("solver_variant", "auto"),
        "acceleration_mode": experiment.get("acceleration_mode", "auto"),
        "hypothesis_id": research.get("hypothesis") or "workspace",
        "load_case": load_case,
        "mesh_level": experiment["mesh_level"],
        "projection": projection,
        "controller": controller,
        "filter": filter_name,
        "geometry": geometry,
        "bc_config": {**boundary,
                      "load_scale": _load_scale(research)},
        "unit_context": unit_context,
        "work_package": {"material": material,
                         "volume_fraction": research.get("constraints", {}).get(
                             "volume_fraction", parameters.get("volfrac", .4))},
        "params": {**parameters, **material, "beta_max": beta_max,
                   "projection": projection, "controller": controller},
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
