"""Task conversion facade kept separate from the queue transport."""


def build_solver_task(experiment: dict) -> dict:
    parameters = dict(experiment["parameters"])
    beta = float(parameters.get("beta", parameters.get("beta_max", 1)))
    projected = beta > 1
    return {
        "task_id": experiment["id"], "experiment_group": experiment["id"],
        "hypothesis_id": "workspace", "load_case": "vertical",
        "mesh_level": experiment["mesh_level"],
        "projection": "heaviside_projection" if projected else "none",
        "controller": "periodic_controller" if projected else "fixed_controller",
        "filter": "density_filter" if projected else "sensitivity_filter",
        "params": {**parameters, "beta_max": max(beta, 2)},
    }

