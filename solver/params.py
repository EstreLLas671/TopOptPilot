"""
参数规范化 — 把实验 Agent 的 ExperimentTask / 任务 JSON 映射为求解引擎
的统一 task_spec，并做校验与默认值填充。

输入来源（两种等价）：
  1. agent.roles.experiment_agent.ExperimentTask（含 load_case / mesh_level /
     params / work_package / projection / controller / filter）
  2. 纯 dict 任务描述（demo 或直接调用）

关键映射：
    mesh_level      → (nelx, nely) 网格尺寸
    load_case       → bc_type 边界条件（vertical→MBB, lateral→cantilever, ...）
    filter          → 滤波插件（sensitivity_filter / density_filter）
    projection      → 投影插件（none / heaviside_projection）
    controller      → 反馈控制器（periodic / gray_feedback / joint_feedback / fixed）
    agent params    → 引擎数值参数（beta_max/p_start/rmin/move/...）
"""

from __future__ import annotations

import copy

# 网格级别 → (nelx, nely)。medium 为经典 99-line 验证过的 60×30。
MESH_GRIDS = {
    "coarse": (30, 15),
    "medium": (60, 30),
    "fine": (90, 45),
}

# 网格级别 → 最大迭代数（change 判据对经典 OC 不可靠，主用迭代上限；
# 经验上 100-150 步柔度已稳定）
MESH_MAX_ITER = {
    "coarse": 80,
    "medium": 150,
    "fine": 200,
}

LOAD_CASE_TO_BC = {
    "vertical": "MBB",
    "mbb": "MBB",
    "lateral": "cantilever",
    "cantilever": "cantilever",
    "l-bracket": "L-bracket",
    "L-bracket": "L-bracket",
    "distributed": "simply_supported",
    "simply_supported": "simply_supported",
    "simply-supported": "simply_supported",
}

FILTER_ALIASES = {
    "PDE_filter": "sensitivity_filter",
    "pde_filter": "sensitivity_filter",
    "sensitivity_filter": "sensitivity_filter",
    "density_filter": "density_filter",
    "density-filter": "density_filter",
}

PROJECTION_ALIASES = {
    "heaviside_projection": "heaviside_projection",
    "Heaviside_projection": "heaviside_projection",
    "none": "none",
    "": "none",
}

CONTROLLER_ALIASES = {
    "joint_feedback_controller": "joint_feedback_controller",
    "gray_feedback_controller": "gray_feedback_controller",
    "periodic_controller": "periodic_controller",
    "fixed_controller": "fixed_controller",
    "": "fixed_controller",
}

ENGINE_DEFAULTS = {
    "p_start": 3.0,
    "rmin": 1.5,
    "move": 0.2,
    "xmin": 1e-3,
    "tol_change": 1e-3,
    "eta": 0.5,
    "max_iter": 200,
    "beta_max": 16,
    "beta_step": 2,
    "beta_interval": 10,
    "gray_threshold": 0.20,
    "E": 1.0,
    "nu": 0.3,
    "volfrac": 0.40,
}


def resolve_geometry(mesh_level: str, geometry=None) -> tuple[int, int]:
    """解析网格尺寸。geometry 优先（"rect_WxH" 或 {"nelx":..,"nely":..}），
    否则按 mesh_level 查表。"""
    if geometry:
        if isinstance(geometry, dict) and geometry.get("nelx") and geometry.get("nely"):
            return int(geometry["nelx"]), int(geometry["nely"])
        if isinstance(geometry, str) and geometry.lower().startswith("rect"):
            # "rect_60x30" / "rect60x30" / "60x30"
            s = geometry.lower().replace(" ", "").replace("rect", "").lstrip("_")
            parts = s.replace("x", " ").replace("*", " ").split()
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
    if mesh_level not in MESH_GRIDS:
        raise ValueError(
            f"未知网格级别: {mesh_level}。支持: {list(MESH_GRIDS)}")
    return MESH_GRIDS[mesh_level]


def resolve_bc(load_case: str) -> str:
    bc = LOAD_CASE_TO_BC.get((load_case or "").strip().lower())
    if bc is None:
        raise ValueError(
            f"未知载荷工况: {load_case}。支持: {sorted(set(LOAD_CASE_TO_BC))}")
    return bc


def normalize_task(task) -> dict:
    """把 ExperimentTask / dict 规范化为引擎 task_spec（含默认值）。

    返回 dict，可直接传给 topopt_engine.run_topopt(task_spec)。
    """
    # --- 抽取原始字段（兼容 dataclass 与 dict） ---
    if isinstance(task, dict):
        raw = copy.deepcopy(task)
    else:
        d = getattr(task, "__dict__", {})
        raw = {
            "task_id": getattr(task, "task_id", ""),
            "experiment_group": getattr(task, "experiment_group", ""),
            "hypothesis_id": getattr(task, "hypothesis_id", ""),
            "load_case": getattr(task, "load_case", ""),
            "mesh_level": getattr(task, "mesh_level", "medium"),
            "params": getattr(task, "params", {}),
            "work_package": getattr(task, "work_package", {}),
            "projection": getattr(task, "projection", ""),
            "controller": getattr(task, "controller", ""),
            "filter": getattr(task, "filter", ""),
            "solver": getattr(task, "solver", ""),
        }
        raw.update({k: v for k, v in d.items() if k not in raw})

    # --- 幂等：已规范化的 spec（含 bc_type/nelx/nely）直接补默认值返回 ---
    if raw.get("bc_type") and raw.get("nelx") and raw.get("nely"):
        out = dict(raw)
        for k, v in ENGINE_DEFAULTS.items():
            if k not in out or out[k] is None:
                out[k] = v
        out.setdefault("controller", "fixed_controller")
        out.setdefault("projection", "none")
        out.setdefault("filter", "sensitivity_filter")
        out.setdefault("mesh_level", "medium")
        out.setdefault("max_iter", MESH_MAX_ITER.get(out["mesh_level"], 200))
        out.setdefault("bc_config", None)
        return out

    params = dict(raw.get("params") or {})
    wp = dict(raw.get("work_package") or {})
    mesh_level = raw.get("mesh_level", "medium") or "medium"

    # --- 网格 ---
    nelx, nely = resolve_geometry(mesh_level, raw.get("geometry"))

    # --- 边界条件 ---
    bc_type = resolve_bc(raw.get("load_case", "vertical"))

    # --- 插件组合 → 物理路径 ---
    filter_id = FILTER_ALIASES.get(
        str(raw.get("filter", "sensitivity_filter")).strip(),
        "sensitivity_filter")
    projection = PROJECTION_ALIASES.get(
        str(raw.get("projection", "none")).strip(), "none")
    controller = CONTROLLER_ALIASES.get(
        str(raw.get("controller", "fixed_controller")).strip(),
        "fixed_controller")

    # --- 数值参数：引擎默认值 <- 任务 params <- 任务包 ---
    spec = {}
    for k, v in ENGINE_DEFAULTS.items():
        if k in ("E", "nu"):
            continue
        spec[k] = params.get(k, v)
    spec["beta_max"] = float(params.get("beta_max", spec["beta_max"]) or 0)
    spec["beta_step"] = float(params.get("beta_step", spec["beta_step"]) or 2)
    spec["beta_interval"] = int(params.get("beta_interval", spec["beta_interval"]) or 10)
    spec["gray_threshold"] = float(params.get("gray_threshold", spec["gray_threshold"]) or 0.20)
    spec["max_iter"] = int(params.get("max_iter", MESH_MAX_ITER.get(mesh_level, 200)))

    material = wp.get("material") or raw.get("material") or {}
    spec["E"] = float(params.get("E", material.get("E", material.get("E_MPa", 1.0))))
    spec["nu"] = float(params.get("nu", material.get("nu", 0.3)))
    spec["volfrac"] = float(params.get("volfrac",
                                       wp.get("volume_fraction", 0.40)))

    # 投影为 none 时强制 fixed 控制器（无 beta 可调度）
    if projection == "none":
        controller = "fixed_controller"

    spec["bc_type"] = bc_type
    spec["nelx"] = nelx
    spec["nely"] = nely
    spec["mesh_level"] = mesh_level
    spec["filter"] = filter_id
    spec["projection"] = projection
    spec["controller"] = controller
    spec["solver"] = str(raw.get("solver", "fe_solver") or "fe_solver")
    spec["task_id"] = str(raw.get("task_id", ""))
    spec["experiment_group"] = str(raw.get("experiment_group", ""))
    spec["hypothesis_id"] = str(raw.get("hypothesis_id", ""))

    # rmin 为空/非正时退化为 1（最小 3×3 邻域）
    spec["rmin"] = max(float(spec["rmin"] or 0), 1.0)
    # 罚指数与投影同时为 none 时至少用 p_start
    spec["p_start"] = max(float(spec["p_start"] or 3.0), 1.0)

    return spec
