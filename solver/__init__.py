"""
TopOptPilot — 求解器模块（方法与求解层）

将 `求解器模块/FE_solver.m` + `求解器模块/OC_solver.m` 集成进 agent 的
可执行拓扑优化引擎。双后端：
  - backend="python"  : numpy/scipy 移植（无 MATLAB 依赖，开箱即用）
  - backend="matlab"  : MATLAB Engine 调用原始 .m 文件（需 matlabengine 包）
  - backend="simulate": 保留旧模拟行为（用于演示预计算）

统一入口：
    from solver.topopt_engine import run_topopt
    result = run_topopt(task)
"""

from solver.fe_solver import FESolver, lk_matrix, compute_sensitivities
from solver.oc_solver import oc_update
from solver.topopt_engine import run_topopt, run_topopt_from_task
from solver.params import normalize_task
from solver.continuation import make_controller, penal_at_iteration
from solver.result_schema import gray_ratio, connected_components, build_result

__all__ = [
    "FESolver", "lk_matrix", "compute_sensitivities", "oc_update",
    "run_topopt", "run_topopt_from_task", "normalize_task",
    "make_controller", "penal_at_iteration",
    "gray_ratio", "connected_components", "build_result",
]
