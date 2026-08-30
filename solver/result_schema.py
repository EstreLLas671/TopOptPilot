"""
结果契约 — 从引擎原始输出构建 ExperimentResult 兼容的结果 dict。

质量指标（与 agent/roles/audit_agent.py 的 ResultAnalyzer 口径一致）：
    gray_ratio            介于 (0.1, 0.9) 的单元比例
    connected_components  物理密度 > 0.5 的连通分量数（8 邻接，忽略单单元碎点）
    max_displacement      位移场最大绝对值（单位模量模型下为无量纲量）

输出 dict 顶层字段与 experiments.experiment_queue.get_all_results()
构造 ExperimentResult 时读取的键一一对应。
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

GRAY_LOW, GRAY_HIGH = 0.1, 0.9
CONNECT_THRESHOLD = 0.5


def gray_ratio(x: np.ndarray) -> float:
    """灰度比例：密度介于 (0.1, 0.9) 的单元占比。"""
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return 0.0
    return float(np.mean((x > GRAY_LOW) & (x < GRAY_HIGH)))


def connected_components(x: np.ndarray, threshold: float = CONNECT_THRESHOLD,
                         min_size: int = 2) -> int:
    """物理密度 > threshold 的连通分量数。

    使用 8 邻接（对角相接触即连通）；忽略少于 min_size 个单元的碎点，
    避免单个浮动单元把良好设计误判为"断连"。
    """
    x = np.asarray(x, dtype=float)
    labeled, n = ndimage.label(x > threshold, structure=np.ones((3,) * x.ndim))
    if n == 0:
        return 0
    sizes = ndimage.sum(x > threshold, labeled, range(1, n + 1))
    return int(np.count_nonzero(sizes >= min_size))


def max_displacement(U: np.ndarray) -> float:
    """位移场最大绝对值。"""
    U = np.asarray(U, dtype=float)
    return float(np.max(np.abs(U))) if U.size else 0.0


def build_result(*, task_spec: dict, status: str, compliance: float,
                 xPhys: np.ndarray, U: np.ndarray, history: list,
                 iterations: int, final_change: float, relative_residual: float,
                 solve_time: float, backend: str = "python",
                 density_design: np.ndarray = None,
                 run_id: str = "") -> dict:
    """组装最终结果 dict（ExperimentResult 兼容 + 物理调试字段）。"""
    # 经典 OC 以迭代上限终止是标准行为，映射到契约的 converged
    if status == "max_iter":
        status = "converged"
    vol_actual = float(np.mean(xPhys))
    gray = gray_ratio(xPhys)
    connected = connected_components(xPhys)
    u_max = max_displacement(U)
    from solver.stress import compute_von_mises, stress_unit_metadata
    unit_metadata = stress_unit_metadata(task_spec)
    stress = None
    stress_error = None
    try:
        stress = compute_von_mises(task_spec, np.asarray(xPhys, dtype=float), U, history)
        if stress.shape != np.asarray(xPhys).shape or not np.isfinite(stress).all():
            raise ValueError("应力场形状或有限性校验失败")
    except Exception as exc:
        stress = None
        stress_error = str(exc)

    result = {
        "run_id": run_id,
        "task_id": task_spec.get("task_id", ""),
        "hypothesis_id": task_spec.get("hypothesis_id", ""),
        "experiment_group": task_spec.get("experiment_group", ""),
        "status": status,
        "objective": {"compliance": float(compliance)},
        "constraints": {"volume_fraction": vol_actual},
        "quality": {
            "gray_ratio": round(gray, 4),
            "connected_components": connected,
            "max_displacement_mm": round(u_max, 4),
            "maximum_von_mises": (float(np.max(stress)) if stress is not None else None),
            **unit_metadata,
            "stress_unavailable_reason": stress_error,
        },
        "solver": {
            "backend": backend,
            "relative_residual": float(relative_residual),
            "cg_iterations": 0,            # 直接稀疏求解，无 PCG 迭代
            "solve_time_seconds": round(solve_time, 3),
            "mesh_level": task_spec.get("mesh_level", "medium"),
            "iterations": int(iterations),
            "final_change": float(final_change),
            "max_iter": int(task_spec.get("max_iter", 200)),
            "penal_final": float(history[-1]["penal"]) if history else None,
            "beta_final": float(history[-1]["beta"]) if history else None,
        },
        "artifacts": {
            "density": np.asarray(xPhys, dtype=float),
            "density_design": (np.asarray(density_design, dtype=float)
                               if density_design is not None else np.asarray(xPhys)),
            "history": history,
            "u_max": round(u_max, 6),
            "stress": stress,
        },
        # 物理调试字段（供测试/演示读取，不进审计）
        "_physics": {
            "nelx": int(task_spec.get("nelx", 0)),
            "nely": int(task_spec.get("nely", 0)),
            "bc_type": task_spec.get("bc_type", ""),
            "volfrac_target": float(task_spec.get("volfrac", 0.40)),
            "controller": task_spec.get("controller", ""),
            "projection": task_spec.get("projection", ""),
        },
    }
    return result
