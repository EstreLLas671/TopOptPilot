"""
拓扑优化引擎 — 主优化循环

统一入口：run_topopt(task_spec) -> result dict（ExperimentResult 兼容）。

物理路径（由 filter / projection / controller 插件组合决定）：
    A. 经典灵敏度滤波（99-line）
         filter=sensitivity_filter, projection=none
         xPhys = x；dc = check(dc, rmin, x)  —— 与 MATLAB 地面真值逐点验证
    B. 密度滤波 SIMP（88-line 去投影）
         filter=density_filter, projection=none
         xPhys = H@x；dc_x = H@dc_xPhys
    C. 密度滤波 + Heaviside 投影（88-line 完整）
         projection=heaviside_projection（自动采用密度滤波路径，保证链式正确）
         xTilde = H@x；xPhys = heaviside(xTilde, beta)
         dc_x = H@(dc_xPhys · heaviside'(xTilde))

beta 由 controller 按迭代 + 实时灰度/连通性反馈调度（solver/continuation.py）；
penal 可选延续（p_start→p_end）。OC 更新作用于设计变量 x，体积约束作用于 x。

停止判据：主用 max_iter（经典 OC 的 change 判据不可靠，见验证记录）；
change < tol_change 时提前收敛。
"""

from __future__ import annotations

import time

import numpy as np

from solver.fe_solver import FESolver, compute_sensitivities
from solver.oc_solver import oc_update
from solver.filters import (
    build_filter_matrix, sensitivity_filter, density_filter,
    adjoint_sensitivity, heaviside, heaviside_derivative,
)
from solver.continuation import make_controller, penal_at_iteration
from solver.result_schema import gray_ratio, connected_components, build_result
from solver.params import normalize_task

__all__ = ["run_topopt", "run_topopt_from_task"]


def run_topopt(task_spec, *, backend: str = "python",
               max_iter_override: int = None, time_limit: float = None,
               progress=None, cancel=None) -> dict:
    """运行一次拓扑优化，返回 ExperimentResult 兼容的 dict。

    task_spec: ExperimentTask 或已规范化的 dict（由 params.normalize_task 处理）。
    backend:   "python"（numpy/scipy）或 "matlab"（MATLAB Engine，见 matlab_backend）。
    time_limit: 秒；超时则返回 status="timeout"（保留已达成的密度/历史）。
    progress:   可选回调 progress(iteration, state)。
    """
    if backend == "matlab":
        from solver.matlab_backend import run_topopt_matlab
        return run_topopt_matlab(task_spec, max_iter_override=max_iter_override,
                                 time_limit=time_limit, progress=progress)

    spec = normalize_task(task_spec)
    t0 = time.time()
    nelx, nely = spec["nelx"], spec["nely"]
    bc_type = spec["bc_type"]
    volfrac = spec["volfrac"]
    projection = spec["projection"]
    filter_id = spec["filter"]
    use_heaviside = projection == "heaviside_projection"

    fe = FESolver(nelx, nely, E=spec["E"], nu=spec["nu"])
    H = build_filter_matrix(nelx, nely, spec["rmin"])
    controller = make_controller(spec["controller"], spec)
    eta = float(spec["eta"])

    max_iter = int(max_iter_override if max_iter_override else spec["max_iter"])
    tol_change = float(spec["tol_change"])
    move = float(spec["move"])
    xmin = float(spec["xmin"])

    initial = spec.get("initial_density")
    if initial is not None:
        from scipy.ndimage import zoom
        initial = np.asarray(initial, dtype=float)
        if initial.ndim == 3:
            initial = initial.mean(axis=0)
        if initial.shape != (nely, nelx):
            initial = zoom(initial, (nely / initial.shape[0], nelx / initial.shape[1]), order=1)
        x = np.clip(initial[:nely, :nelx], spec.get("xmin", 1e-3), 1.0)
        x *= volfrac / max(float(x.mean()), 1e-12)
        x = np.clip(x, spec.get("xmin", 1e-3), 1.0)
    else:
        x = np.full((nely, nelx), volfrac)
    xPhys = x.copy()

    history = []
    status = "max_iter"
    final = None
    gray_prev = None
    connected_prev = None

    cancelled = False
    for it in range(1, max_iter + 1):
        if cancel is not None and cancel():
            status = "cancelled"
            cancelled = True
            break
        beta = controller.beta(it, gray_prev, connected_prev)
        penal = penal_at_iteration(it, spec)

        # ---- 前向：设计变量 x -> 物理密度 xPhys ----
        if use_heaviside and beta > 0:
            xTilde = density_filter(x, H)
            xPhys = heaviside(xTilde, beta, eta)
        elif filter_id == "density_filter":
            xPhys = density_filter(x, H)
        else:
            xPhys = x

        # ---- 求解 K·U = F（xPhys 为当前物理密度）----
        sol = fe.solve(xPhys, penal, bc_type, spec.get("bc_config"))

        # ---- 灵敏度链式求导 dC/dx ----
        if use_heaviside and beta > 0:
            dc_xPhys = compute_sensitivities(xPhys, sol["U"], penal, fe.KE, nelx, nely)
            dc_xt = dc_xPhys * heaviside_derivative(xTilde, beta, eta)
            dc_x = adjoint_sensitivity(dc_xt, H)
            dv_x = adjoint_sensitivity(heaviside_derivative(xTilde, beta, eta), H)
            volume_fn = lambda candidate, b=beta: float(
                heaviside(density_filter(candidate, H), b, eta).mean())
        elif filter_id == "density_filter":
            dc_xPhys = compute_sensitivities(xPhys, sol["U"], penal, fe.KE, nelx, nely)
            dc_x = adjoint_sensitivity(dc_xPhys, H)
            dv_x = adjoint_sensitivity(np.ones_like(xPhys), H)
            volume_fn = lambda candidate: float(density_filter(candidate, H).mean())
        else:
            dc_x = sensitivity_filter(
                compute_sensitivities(x, sol["U"], penal, fe.KE, nelx, nely),
                H, x)
            dv_x = np.ones_like(x)
            volume_fn = lambda candidate: float(candidate.mean())

        # ---- OC 更新设计变量 ----
        if not np.all(np.isfinite(dc_x)):
            status = "failed"
            break
        try:
            xnew, info = oc_update(x, dc_x, volfrac, {"move": move, "xmin": xmin,
                                                       "volume_sensitivity": dv_x,
                                                       "volume_fn": volume_fn})
        except (ValueError, FloatingPointError):
            status = "failed"
            break

        # ---- 指标 ----
        change = float(np.max(np.abs(xnew - x)))
        x = xnew
        compliance = float(sol["compliance"])
        # 求解不可信（残差大 → 近奇异）或柔度非有限 → 判失败
        if (not np.isfinite(compliance) or
                sol["relative_residual"] > 1e-3):
            status = "failed"
            break
        gray_prev = gray_ratio(xPhys)
        connected_prev = connected_components(xPhys)

        history.append({
            "iteration": it,
            "compliance": compliance,
            "change": change,
            "volume_fraction": float(xPhys.mean()),
            "gray_ratio": gray_prev,
            "connected": connected_prev,
            "beta": beta,
            "penal": penal,
            "lambda": float(info["lambda"]),
            "residual": float(sol["relative_residual"]),
        })
        final = (sol, info, xPhys, x)

        if progress is not None:
            try:
                progress(it, history[-1])
            except Exception:
                pass

        if cancel is not None and cancel():
            status = "cancelled"
            cancelled = True
            break

        if change < tol_change:
            status = "converged"
            break
        if time_limit is not None and (time.time() - t0) > time_limit:
            status = "timeout"
            break

    # ---- 收尾：由最终设计变量 x 重算物理密度并求解，保证结果一致 ----
    if cancelled:
        return build_result(task_spec=spec, status="cancelled",
                            compliance=float(final[0]["compliance"]) if final else float("nan"),
                            xPhys=xPhys, U=final[0]["U"] if final else np.zeros(fe.ndof),
                            history=history, iterations=len(history),
                            final_change=history[-1]["change"] if history else float("nan"),
                            relative_residual=float(final[0]["relative_residual"]) if final else float("nan"),
                            solve_time=time.time() - t0, backend="python",
                            density_design=x)

    if final is None or np.isnan(xPhys).any():
        return build_result(task_spec=spec, status="failed",
                            compliance=float("nan"), xPhys=xPhys,
                            U=np.zeros(fe.ndof), history=history,
                            iterations=len(history), final_change=float("nan"),
                            relative_residual=float("nan"),
                            solve_time=time.time() - t0, backend="python",
                            density_design=x)

    beta_last = history[-1]["beta"] if history else 0.0
    penal_last = penal_at_iteration(len(history), spec)
    if use_heaviside and beta_last > 0:
        xPhys_final = heaviside(density_filter(x, H), beta_last, eta)
    elif filter_id == "density_filter":
        xPhys_final = density_filter(x, H)
    else:
        xPhys_final = x

    sol_final = fe.solve(xPhys_final, penal_last, bc_type, spec.get("bc_config"))

    return build_result(
        task_spec=spec, status=status,
        compliance=float(sol_final["compliance"]),
        xPhys=xPhys_final, U=sol_final["U"], history=history,
        iterations=len(history),
        final_change=history[-1]["change"],
        relative_residual=float(sol_final["relative_residual"]),
        solve_time=time.time() - t0, backend="python",
        density_design=x,
    )


def run_topopt_from_task(task, backend: str = "python", **kw) -> dict:
    """从 ExperimentTask / 任务 JSON 直接运行（内部调用 run_topopt）。"""
    return run_topopt(task, backend=backend, **kw)
