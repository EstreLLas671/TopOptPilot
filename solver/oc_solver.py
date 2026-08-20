"""
OC 求解器 — `求解器模块/OC_solver.m` 的 Python (numpy) 移植

与 MATLAB 版本逐行语义一致：
  - 可配置的数值参数和单步密度变化上限（xmin / move）
  - 被动空域 / 被动实体域 / active_mask
  - 体积约束的可行性检查（含舍入容差截断）
  - 拉格朗日乘子二分搜索 + info 诊断信息
"""

from __future__ import annotations

import numpy as np


def _set_default(opts: dict, name: str, value):
    if name not in opts or opts[name] is None:
        opts[name] = value
    return opts


def _make_mask(value, expected_size, default_value) -> np.ndarray:
    """构建逻辑掩码。空值 → 全 default_value；否则校验形状与合法性。"""
    if value is None or len(np.asarray(value)) == 0:
        return np.full(expected_size, default_value, dtype=bool)
    value = np.asarray(value)
    if value.shape != expected_size:
        raise ValueError(
            f"掩码形状应为 {expected_size}，实际 {value.shape}")
    if value.dtype != bool and not np.all(np.isfinite(value)):
        raise ValueError("掩码必须是逻辑数组或有限数值数组")
    return value.astype(bool)


def oc_update(x: np.ndarray, dc: np.ndarray, volfrac: float,
              opts: dict = None) -> tuple[np.ndarray, dict]:
    """增强 OC 密度更新器（Python 移植 OC_solver.m）。

    参数:
        x:       当前密度场，任意形状（如 (nely, nelx)）
        dc:      滤波后的柔顺度灵敏度，形状与 x 一致
        volfrac: 体积分数目标，0~1
        opts:    可选字段
            xmin           密度下限，默认 1e-3
            move           每步最大密度变化，默认 0.2
            tol_lambda     拉格朗日乘子二分精度，默认 1e-4
            max_bisect     最大二分次数，默认 100
            passive_void   被动空域掩码，始终为 xmin
            passive_solid  被动实体掩码，始终为 1
            active_mask    可设计单元掩码

    返回:
        (xnew, info)
        info: {lambda, bisect_iterations, volume, volume_fraction,
               volume_error, active_elements, converged}
    """
    opts = dict(opts or {})
    _set_default(opts, "xmin", 1e-3)
    _set_default(opts, "move", 0.2)
    _set_default(opts, "tol_lambda", 1e-4)
    _set_default(opts, "max_bisect", 100)
    _set_default(opts, "passive_void", None)
    _set_default(opts, "passive_solid", None)
    _set_default(opts, "active_mask", None)
    _set_default(opts, "volume_sensitivity", None)
    _set_default(opts, "volume_fn", None)

    x = np.asarray(x, dtype=float)
    dc = np.asarray(dc, dtype=float)
    if not np.all(np.isfinite(x)) or x.size == 0:
        raise ValueError("x 必须为有限非空数值")
    if dc.shape != x.shape or not np.all(np.isfinite(dc)):
        raise ValueError("dc 必须为有限数值且与 x 同形状")
    if not (0 <= volfrac <= 1):
        raise ValueError(f"volfrac 必须位于 [0,1]: {volfrac}")

    xmin = float(opts["xmin"])
    move = float(opts["move"])
    tol_lambda = float(opts["tol_lambda"])
    max_bisect = int(opts["max_bisect"])
    if not (0 < xmin < 1):
        raise ValueError(f"opts.xmin 必须位于 (0,1): {xmin}")
    if move <= 0:
        raise ValueError(f"opts.move 必须为正: {move}")
    if tol_lambda <= 0:
        raise ValueError(f"opts.tol_lambda 必须为正: {tol_lambda}")
    if max_bisect <= 0:
        raise ValueError(f"opts.max_bisect 必须为正整数: {max_bisect}")

    n = x.size
    passive_void = _make_mask(opts["passive_void"], x.shape, False)
    passive_solid = _make_mask(opts["passive_solid"], x.shape, False)
    if np.any(passive_void & passive_solid):
        raise ValueError("passive_void 与 passive_solid 不得重叠")

    if opts["active_mask"] is None:
        active_mask = ~(passive_void | passive_solid)
    else:
        active_mask = _make_mask(opts["active_mask"], x.shape, True)
        if np.any(active_mask & (passive_void | passive_solid)):
            raise ValueError("单元不能同时为可设计与被动")

    # 未被显式标记为可设计的单元固定在当前密度
    fixed_mask = ~active_mask
    fixed_values = np.minimum(1.0, np.maximum(xmin, x))
    fixed_values[passive_void] = xmin
    fixed_values[passive_solid] = 1.0

    target_volume = volfrac * n
    fixed_volume = float(fixed_values[fixed_mask].sum())
    n_active = int(np.count_nonzero(active_mask))
    min_volume = fixed_volume + n_active * xmin
    max_volume = fixed_volume + n_active
    volume_tolerance = max(tol_lambda, 1e-10) * max(1, n)

    if (target_volume < min_volume - volume_tolerance or
            target_volume > max_volume + volume_tolerance):
        raise ValueError(
            f"目标体积 {target_volume:.6g} 不可行。给定掩码下可行总体积为 "
            f"[{min_volume:.6g}, {max_volume:.6g}]")

    # 对几乎可行的目标体积截断，避免舍入误差误报
    target_volume = min(max(target_volume, min_volume), max_volume)

    xnew = fixed_values.copy()
    if n_active == 0:
        return xnew, _build_info(
            np.nan, 0, xnew, target_volume, active_mask, True)

    # 灵敏度通常为负；设下限保护 sqrt() 并让这些单元向低密度更新
    dv = (np.ones_like(x) if opts["volume_sensitivity"] is None
          else np.asarray(opts["volume_sensitivity"], dtype=float))
    if dv.shape != x.shape or not np.all(np.isfinite(dv)) or np.any(dv < 0):
        raise ValueError("volume_sensitivity 必须为与 x 同形状的非负有限数组")
    dv = np.maximum(dv, 1e-12)
    sensitivity_ratio = np.maximum(1e-30, -dc[active_mask] / dv[active_mask])
    x_active = np.minimum(1.0, np.maximum(xmin, x[active_mask]))
    volume_fn = opts["volume_fn"] or (lambda value: float(np.asarray(value).mean()))

    l1, l2 = 0.0, 1e5
    bisect_iterations = 0
    converged = False

    for it in range(1, max_bisect + 1):
        bisect_iterations = it
        lam = 0.5 * (l1 + l2)
        candidate = x_active * np.sqrt(sensitivity_ratio / lam)
        candidate = np.maximum(
            xmin,
            np.maximum(x_active - move,
                       np.minimum(1.0, np.minimum(x_active + move, candidate))))
        xnew[active_mask] = candidate
        current_volume_fraction = float(volume_fn(xnew))
        if current_volume_fraction > volfrac:
            l1 = lam
        else:
            l2 = lam
        if (l2 - l1) <= tol_lambda:
            converged = True
            break

    # 用最终区间的中点重算密度，确保 lambda 与 xnew 对应
    lam = 0.5 * (l1 + l2)
    candidate = x_active * np.sqrt(sensitivity_ratio / lam)
    candidate = np.maximum(
        xmin,
        np.maximum(x_active - move,
                   np.minimum(1.0, np.minimum(x_active + move, candidate))))
    xnew[active_mask] = candidate
    xnew[passive_void] = xmin
    xnew[passive_solid] = 1.0

    info = _build_info(lam, bisect_iterations, xnew, target_volume,
                       active_mask, converged)
    info["physical_volume_fraction"] = float(volume_fn(xnew))
    info["physical_volume_error"] = info["physical_volume_fraction"] - volfrac
    return xnew, info


def _build_info(lam, bisect_iterations, xnew, target_volume,
                active_mask, converged) -> dict:
    return {
        "lambda": float(lam),
        "bisect_iterations": bisect_iterations,
        "volume": float(xnew.sum()),
        "volume_fraction": float(xnew.mean()),
        "target_volume": float(target_volume),
        "volume_error": float(xnew.sum() - target_volume),
        "active_elements": int(np.count_nonzero(active_mask)),
        "converged": bool(converged),
    }
