"""
MATLAB 双后端 — MATLAB Engine 调用原始 `求解器模块/*.m` 求解

架构（Python 移植 + MATLAB Engine 双后端）：
    backend="python"   默认。numpy/scipy 移植，开箱即用、无外部依赖。
                       由 solver/topopt_engine.run_topopt 完整实现。
    backend="matlab"   可选的 MATLAB Engine 后端。通过 matlabengine pip 包
                       启动本地 MATLAB，把规范化后的 task_spec 以 JSON 字符串
                       传给 `求解器模块/` 下的驱动函数（默认 top3d_main），
                       由其执行原始 FE_solver.m / OC_solver.m 并写回结果 JSON。

为何默认 Python：
    - matlabengine 未预装，Python 移植与 MATLAB 地面真值已逐点核对
      （见 _ground_truth/verify_port.py），结果可靠且可测试；
    - MATLAB 路径依赖本地安装的 MATLAB + Engine API，属于生产增强选项。

如何启用 MATLAB：
    1. pip install matlabengine
    2. 安装 MATLAB（Engine 需要 Runtime/完整安装，见 .env.example 的 MATLAB_PATH）
    3. 在 `求解器模块/` 提供 MATLAB 驱动函数（默认名 top3d_main）：
           function result_path = top3d_main(task_json)
           输入 task_json 为规范化 task_spec 的 JSON 字符串；
           应执行 FE_solver.m + OC_solver.m 主循环，并把结果以
           实验契约 dict 的 JSON 写入文件，返回该文件路径
           （也可直接以 MATLAB struct 返回，引擎会自动转换）。
       可通过环境变量 TOPOPT_MATLAB_DRIVER 覆盖入口函数名。

降级保证：MATLAB 不可用 / 调用失败时自动回退 Python 引擎
（backend 标记为 "matlab_fallback_python"），管线永不崩溃。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

from solver.result_schema import gray_ratio, connected_components

__all__ = ["is_matlab_available", "run_topopt_matlab"]

logger = logging.getLogger("TopOptPilot.Solver")

# `求解器模块/` 目录（相对本文件上溯两级到项目根）
_SOLVER_M_DIR = Path(__file__).resolve().parent.parent / "求解器模块"

# MATLAB 驱动入口函数名（可用环境变量 TOPOPT_MATLAB_DRIVER 覆盖）
_DEFAULT_DRIVER = "top3d_main"


def is_matlab_available() -> bool:
    """matlabengine 是否已安装（Matlab Engine 可用性的粗略探测）。

    仅捕获 ImportError：未安装 pip 包 / 找不到 Python 版 Engine 均返回 False。
    """
    try:
        import matlabengine  # noqa: F401
        return True
    except ImportError:
        return False


def run_topopt_matlab(task_spec, *, max_iter_override: int = None,
                      time_limit: float = None, progress=None) -> dict:
    """MATLAB Engine 后端入口，返回 ExperimentResult 兼容的 dict。

    与 solver.topopt_engine.run_topopt 同签名（backend 固定为 matlab）。

    - matlabengine 未安装 → 记录告警并降级 Python 引擎。
    - MATLAB 启动 / 驱动调用 / 结果解析任一失败 → 记录错误并降级 Python 引擎。
    - 成功时返回 MATLAB 结果；backend 标记为 "matlab"。

    降级后 result["solver"]["backend"] = "matlab_fallback_python"，
    保证下游实验管线（experiments/*）照常读取，永不崩溃。

    局限：MATLAB 引擎调用是阻塞的，Python 侧无法中断进行中的
    eng.driver(...) 调用；time_limit 以 "time_limit" 键注入 task_spec，
    由 MATLAB 驱动自行检查。progress 回调同样不向 MATLAB 转发
    （驱动可把迭代历史写入结果 JSON 的 history 字段带回）。
    """
    if not is_matlab_available():
        logger.warning(
            "MATLAB 后端不可用：matlabengine 未安装。请先执行 "
            "`pip install matlabengine` 并安装 MATLAB Runtime；当前将降级 "
            "为 Python 引擎（backend='matlab_fallback_python'）。")
        return _fallback_to_python(task_spec, max_iter_override, time_limit,
                                   progress, reason="matlabengine_not_installed")

    eng = None
    try:
        import matlab.engine

        logger.info("启动 MATLAB Engine …")
        eng = matlab.engine.start_matlab()
        _configure_matlab_path(eng)

        # 规范化任务，并把运行期覆盖项注入（max_iter / time_limit）
        spec = _normalized(task_spec)
        if max_iter_override is not None:
            spec["max_iter"] = int(max_iter_override)
        if time_limit is not None:
            spec["time_limit"] = float(time_limit)

        driver_name = os.environ.get("TOPOPT_MATLAB_DRIVER", _DEFAULT_DRIVER)
        logger.info("调用 MATLAB 驱动 %s …", driver_name)
        task_json = json.dumps(_jsonable(spec), ensure_ascii=False)

        driver = getattr(eng, driver_name)
        raw = driver(task_json)                      # 阻塞调用（最佳努力）
        data = _read_matlab_output(raw)
        return _normalize_matlab_result(data, spec)
    except Exception as exc:                          # noqa: BLE001 — 尽力降级
        logger.error("MATLAB 后端执行失败（%s），降级为 Python 引擎",
                     exc, exc_info=True)
        return _fallback_to_python(task_spec, max_iter_override, time_limit,
                                   progress, reason="matlab_error")
    finally:
        if eng is not None:
            try:
                eng.quit()
            except Exception:                         # noqa: BLE001
                logger.debug("关闭 MATLAB Engine 失败（可忽略）")


# ---------------------------------------------------------------------------
# MATLAB 路径辅助
# ---------------------------------------------------------------------------

def _normalized(task_spec) -> dict:
    """把任意任务描述规范化为 MATLAB 可用的 task_spec dict。"""
    from solver.params import normalize_task
    return normalize_task(task_spec)


def _configure_matlab_path(eng) -> None:
    """把 `求解器模块/` 加入 MATLAB 路径（nargout=0）。"""
    path = _SOLVER_M_DIR.resolve().as_posix()        # C:/…/求解器模块
    logger.info("将 %s 加入 MATLAB 路径", path)
    eng.addpath(path, nargout=0)


def _jsonable(obj):
    """递归把 numpy 标量/数组等转换为可 JSON 序列化对象。"""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# MATLAB 结果解析
# ---------------------------------------------------------------------------

def _read_matlab_output(raw) -> dict:
    """驱动返回值 → 结果 dict。

    支持两种约定（与文档一致，保证健壮性）：
      - str  → 结果 JSON 文件路径，读取并解析；
      - dict → MATLAB struct 自动转换的结果 dict，直接使用。
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        path = raw.strip()
        if not path:
            raise ValueError("MATLAB 驱动返回了空路径")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError(f"MATLAB 结果 JSON 应为对象，实际: {type(data)}")
        return data
    raise TypeError(f"无法解析 MATLAB 驱动返回值类型: {type(raw)}")


def _normalize_matlab_result(data: dict, spec: dict) -> dict:
    """把 MATLAB 结果 JSON 映射为实验契约 dict，缺失字段取默认值。

    若 density 缺失/为空则抛 ValueError，触发上层降级 Python。
    """
    density = np.asarray(data.get("density"), dtype=float)
    if density.ndim == 0 or density.size == 0:
        raise ValueError("MATLAB 结果缺少有效的 density 数组")
    density_design = np.asarray(data.get("density_design", density), dtype=float)
    if density_design.size == 0:
        density_design = density

    history = list(data.get("history") or [])
    status = str(data.get("status", "converged"))
    if status == "max_iter":                     # 契约只接受三种状态
        status = "converged"

    gray = float(data.get("gray_ratio", gray_ratio(density)))
    connected = int(data.get("connected_components",
                             connected_components(density)))
    u_max = float(data.get("u_max", 0.0))
    max_disp = float(data.get("max_displacement_mm",
                              data.get("max_displacement", u_max)))

    return {
        "run_id": str(data.get("run_id", "")),
        "task_id": str(data.get("task_id", spec.get("task_id", ""))),
        "hypothesis_id": str(data.get("hypothesis_id",
                                      spec.get("hypothesis_id", ""))),
        "experiment_group": str(data.get("experiment_group",
                                         spec.get("experiment_group", ""))),
        "status": status,
        "objective": {"compliance": float(data.get("compliance", float("nan")))},
        "constraints": {"volume_fraction": float(
            data.get("volume_fraction", spec.get("volfrac", 0.40)))},
        "quality": {
            "gray_ratio": round(gray, 4),
            "connected_components": connected,
            "max_displacement_mm": round(max_disp, 4),
        },
        "solver": {
            "backend": "matlab",
            "relative_residual": float(data.get("relative_residual",
                                                float("nan"))),
            "cg_iterations": int(data.get("cg_iterations", 0)),
            "solve_time_seconds": round(float(data.get("solve_time_seconds",
                                                       0.0)), 3),
            "mesh_level": spec.get("mesh_level", "medium"),
            "iterations": int(data.get("iterations", len(history))),
            "final_change": float(data.get("final_change", float("nan"))),
            "max_iter": int(data.get("max_iter", spec.get("max_iter", 200))),
            "penal_final": data.get("penal_final"),
            "beta_final": data.get("beta_final"),
        },
        "artifacts": {
            "density": density,
            "density_design": density_design,
            "history": history,
            "u_max": round(u_max, 6),
        },
    }


# ---------------------------------------------------------------------------
# Python 降级路径
# ---------------------------------------------------------------------------

def _fallback_to_python(task_spec, max_iter_override, time_limit, progress,
                        reason: str) -> dict:
    """降级：调用 Python 引擎（backend="python"）并改写 backend 标记。"""
    from solver.topopt_engine import run_topopt
    logger.warning("降级至 Python 引擎（reason=%s）", reason)
    result = run_topopt(task_spec, backend="python",
                        max_iter_override=max_iter_override,
                        time_limit=time_limit, progress=progress)
    result["solver"]["backend"] = "matlab_fallback_python"
    return result
