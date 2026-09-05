"""Deterministic 3-D SIMP optimizer with genuine Hex8 finite elements.

The default F2 mesh is deliberately small enough for a local workstation, but
every objective and displacement is obtained from K u = f, not a surrogate.
"""

from __future__ import annotations

import time
from itertools import product

import numpy as np
from scipy import ndimage, sparse
from scipy.sparse.linalg import spsolve

from solver.result_schema import build_result, connected_components, gray_ratio


def _hex8_stiffness(E: float, nu: float) -> np.ndarray:
    lam, mu = E * nu / ((1 + nu) * (1 - 2 * nu)), E / (2 * (1 + nu))
    D = np.array([[lam + 2 * mu, lam, lam, 0, 0, 0],
                  [lam, lam + 2 * mu, lam, 0, 0, 0],
                  [lam, lam, lam + 2 * mu, 0, 0, 0],
                  [0, 0, 0, mu, 0, 0], [0, 0, 0, 0, mu, 0],
                  [0, 0, 0, 0, 0, mu]], dtype=float)
    signs = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                      [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=float)
    ke = np.zeros((24, 24))
    for xi, eta, zeta in product((-1 / np.sqrt(3), 1 / np.sqrt(3)), repeat=3):
        natural = np.column_stack((
            signs[:, 0] * (1 + signs[:, 1] * eta) * (1 + signs[:, 2] * zeta) / 8,
            signs[:, 1] * (1 + signs[:, 0] * xi) * (1 + signs[:, 2] * zeta) / 8,
            signs[:, 2] * (1 + signs[:, 0] * xi) * (1 + signs[:, 1] * eta) / 8,
        ))
        # Unit cube maps [-1,1]^3 with J=0.5I.
        grad = natural * 2.0
        B = np.zeros((6, 24))
        for node, (dx, dy, dz) in enumerate(grad):
            col = 3 * node
            B[:, col:col + 3] = [[dx, 0, 0], [0, dy, 0], [0, 0, dz],
                                  [dy, dx, 0], [0, dz, dy], [dz, 0, dx]]
        ke += B.T @ D @ B * 0.125
    return (ke + ke.T) / 2


def _connectivity(nx: int, ny: int, nz: int) -> np.ndarray:
    def node(i, j, k):
        return (k * (ny + 1) + j) * (nx + 1) + i
    elements = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                nodes = [node(i, j, k), node(i + 1, j, k), node(i + 1, j + 1, k),
                         node(i, j + 1, k), node(i, j, k + 1), node(i + 1, j, k + 1),
                         node(i + 1, j + 1, k + 1), node(i, j + 1, k + 1)]
                elements.append(np.array([[3*n, 3*n+1, 3*n+2] for n in nodes]).ravel())
    return np.asarray(elements, dtype=int)


def _node_id(i: int, j: int, k: int, nx: int, ny: int) -> int:
    return (k * (ny + 1) + j) * (nx + 1) + i


def _boundary_conditions_3d(
    nx: int, ny: int, nz: int, load_case: str, load_scale: float,
) -> tuple[np.ndarray, np.ndarray, str]:
    case = str(load_case or "cantilever").strip().lower().replace("_", "-")
    ndof = 3 * (nx + 1) * (ny + 1) * (nz + 1)
    force = np.zeros(ndof)
    if case == "mbb":
        fixed = [3 * _node_id(0, j, k, nx, ny)
                 for k in range(nz + 1) for j in range(ny + 1)]
        support_a = _node_id(nx, 0, 0, nx, ny)
        support_b = _node_id(nx, ny, 0, nx, ny)
        fixed.extend([3 * support_a + 1, 3 * support_a + 2, 3 * support_b + 2])
        load_node = _node_id(0, ny, round(nz / 2), nx, ny)
        canonical = "MBB"
    elif case == "simply-supported":
        left = _node_id(0, 0, 0, nx, ny)
        right = _node_id(nx, 0, 0, nx, ny)
        back = _node_id(0, 0, nz, nx, ny)
        fixed = [3 * left, 3 * left + 1, 3 * left + 2,
                 3 * right + 1, 3 * right + 2, 3 * back + 1]
        load_node = _node_id(round(nx / 2), ny, round(nz / 2), nx, ny)
        canonical = "simply_supported"
    elif case == "l-bracket":
        fixed = [3 * _node_id(0, j, k, nx, ny) + direction
                 for k in range(nz + 1) for j in range(ny + 1)
                 for direction in range(3)]
        load_node = _node_id(nx, 0, round(nz / 2), nx, ny)
        canonical = "L-bracket"
    elif case == "cantilever":
        fixed = [3 * _node_id(0, j, k, nx, ny) + direction
                 for k in range(nz + 1) for j in range(ny + 1)
                 for direction in range(3)]
        load_node = _node_id(nx, round(ny / 2), round(nz / 2), nx, ny)
        canonical = "cantilever"
    else:
        raise ValueError(
            f"Unsupported Python 3D load case {load_case!r}; "
            "expected MBB, cantilever, simply_supported or L-bracket"
        )
    force[3 * load_node + 1] = -float(load_scale)
    fixed_array = np.unique(np.asarray(fixed, dtype=int))
    free = np.setdiff1d(np.arange(ndof), fixed_array)
    return fixed_array, force, canonical


def _domain_mask_3d(nx: int, ny: int, nz: int, load_case: str,
                    geometry: dict | None = None) -> np.ndarray:
    mask = np.ones((nz, ny, nx), dtype=bool)
    if str(load_case).strip().lower().replace("_", "-") != "l-bracket":
        return mask
    geometry = geometry or {}
    cut_width = max(1, min(nx - 1, round(float(geometry.get("cut_width_ratio", 0.5)) * nx)))
    cut_height = max(1, min(ny - 1, round(float(geometry.get("cut_height_ratio", 0.5)) * ny)))
    corner = str(geometry.get("cut_corner", "upper_right")).lower()
    row_slice = slice(ny - cut_height, ny) if corner.startswith("upper") else slice(0, cut_height)
    column_slice = slice(nx - cut_width, nx) if corner.endswith("right") else slice(0, cut_width)
    mask[:, row_slice, column_slice] = False
    return mask


def _filter_kernel(rmin: float) -> np.ndarray:
    radius = max(1, int(np.ceil(rmin)) - 1)
    coords = np.indices((2 * radius + 1,) * 3) - radius
    distance = np.sqrt(np.sum(coords * coords, axis=0))
    return np.maximum(0.0, rmin - distance)


def _project(value: np.ndarray, beta: float, eta: float = .5) -> np.ndarray:
    if beta <= 1:
        return value
    denominator = np.tanh(beta * eta) + np.tanh(beta * (1 - eta))
    return (np.tanh(beta * eta) + np.tanh(beta * (value - eta))) / denominator


def _project_derivative(value: np.ndarray, beta: float, eta: float = .5) -> np.ndarray:
    if beta <= 1:
        return np.ones_like(value)
    denominator = np.tanh(beta * eta) + np.tanh(beta * (1 - eta))
    return beta * (1 - np.tanh(beta * (value - eta)) ** 2) / denominator


def run_topopt3d(task: dict, progress=None) -> dict:
    params = dict(task.get("params") or {})
    grid = params.get("grid3d") or ([12, 4, 3] if task.get("mesh_level") == "coarse3d"
                                    else [18, 6, 4])
    nx, ny, nz = map(int, grid)
    volfrac = float(params.get("volfrac", 0.4))
    penal = float(params.get("penal", 3.0))
    beta = float(params.get("beta", 1.0))
    beta_max = float(params.get("beta_max", beta))
    controller = str(task.get("controller") or params.get("controller") or "fixed_controller")
    projected = task.get("projection") == "heaviside_projection"
    rmin = float(params.get("rmin", 1.5))
    max_iter = int(params.get("max_iter", 40))
    min_iter = min(int(params.get("min_iter", 1)), max_iter)
    E0, Emin, nu = float(params.get("E", 1.0)), 1e-6, float(params.get("nu", 0.3))
    start = time.time()
    ke, edof = _hex8_stiffness(1.0, nu), _connectivity(nx, ny, nz)
    ndof = 3 * (nx + 1) * (ny + 1) * (nz + 1)
    rows = np.repeat(edof, 24, axis=1).ravel()
    cols = np.tile(edof, (1, 24)).ravel()
    load_scale = float((task.get("bc_config") or {}).get("load_scale", 1.0))
    fixed, force, canonical_case = _boundary_conditions_3d(
        nx, ny, nz, str(task.get("load_case") or "cantilever"), load_scale,
    )
    free = np.setdiff1d(np.arange(ndof), fixed)
    domain_mask = _domain_mask_3d(
        nx, ny, nz, canonical_case, dict(task.get("geometry") or {}),
    )
    initial = params.get("initial_density")
    if initial is not None:
        initial = np.asarray(initial, dtype=float)
        if initial.ndim == 2:
            initial = np.repeat(initial[None, :, :], nz, axis=0)
        density = ndimage.zoom(initial, (nz / initial.shape[0], ny / initial.shape[1],
                                         nx / initial.shape[2]), order=1)[:nz, :ny, :nx]
        density = np.clip(density, 1e-3, 1.0)
        density = np.clip(density * volfrac / max(float(density.mean()), 1e-12), 1e-3, 1.0)
    else:
        density = np.full((nz, ny, nx), volfrac)
    density[~domain_mask] = 1e-3
    kernel = _filter_kernel(rmin); denom = ndimage.convolve(np.ones_like(density), kernel, mode="constant")
    history, U = [], np.zeros(ndof)
    relative_residual, change = 0.0, 1.0
    target_beta = beta_max if controller == "periodic_controller" and projected else beta
    status = "max_iter"
    for iteration in range(1, max_iter + 1):
        if not projected:
            beta_current = 1.0
        elif controller == "periodic_controller":
            beta_current = min(beta_max, beta * 2.0 ** max(0, (iteration - 1) // 20))
        else:
            beta_current = beta
        filtered = ndimage.convolve(density, kernel, mode="constant") / denom
        physical = _project(filtered, beta_current) if projected else density
        flat = physical.ravel()
        scale = Emin + flat ** penal * (E0 - Emin)
        values = (scale[:, None, None] * ke).ravel()
        K = sparse.coo_matrix((values, (rows, cols)), shape=(ndof, ndof)).tocsr()
        K = (K + K.T) * 0.5
        U[:] = 0.0
        U[free] = spsolve(K[free][:, free], force[free])
        residual = K @ U - force
        relative_residual = float(np.linalg.norm(residual[free]) / max(np.linalg.norm(force[free]), 1e-12))
        ue = U[edof]
        ce = np.einsum("ei,ij,ej->e", ue, ke, ue).reshape(density.shape)
        compliance = float(np.sum(scale.reshape(density.shape) * ce))
        dc_physical = -penal * (E0 - Emin) * physical ** (penal - 1) * ce
        if projected:
            derivative = _project_derivative(filtered, beta_current)
            dc = ndimage.convolve((dc_physical * derivative) / denom, kernel, mode="constant")
            dv = ndimage.convolve(derivative / denom, kernel, mode="constant")
            volume_fn = lambda value: float(_project(
                ndimage.convolve(value, kernel, mode="constant") / denom,
                beta_current)[domain_mask].mean())
        else:
            dc = (ndimage.convolve(density * dc_physical, kernel, mode="constant") /
                  np.maximum(density * denom, 1e-9))
            dv = np.ones_like(density)
            volume_fn = lambda value: float(value[domain_mask].mean())
        low, high = 0.0, 1e9
        move = float(params.get(
            "move", .2 if beta_current <= 2 else (.1 if beta_current <= 4 else .05)
        ))
        while (high - low) / (high + low + 1e-12) > 1e-4:
            mid = 0.5 * (low + high)
            candidate = np.maximum(1e-3, np.maximum(density - move,
                np.minimum(1.0, np.minimum(density + move,
                    density * np.sqrt(np.maximum(0, -dc / np.maximum(dv * mid, 1e-30)))))))
            if volume_fn(candidate) > volfrac: low = mid
            else: high = mid
        candidate[~domain_mask] = 1e-3
        change = float(np.max(np.abs(candidate - density))); density = candidate
        candidate_filtered = ndimage.convolve(density, kernel, mode="constant") / denom
        candidate_physical = _project(candidate_filtered, beta_current) if projected else density
        item = {"iteration": iteration, "compliance": compliance, "change": change,
                "volume_fraction": float(candidate_physical.mean()),
                "gray_ratio": gray_ratio(candidate_physical),
                "connected": connected_components(candidate_physical), "beta": beta_current,
                "penal": penal, "residual": relative_residual}
        history.append(item)
        if progress: progress(iteration, item)
        if iteration >= min_iter and change < 1e-3 and beta_current >= target_beta:
            status = "converged"
            break
    final_beta = float(history[-1]["beta"]) if history else 1.0
    filtered = ndimage.convolve(density, kernel, mode="constant") / denom
    physical = _project(filtered, final_beta) if projected else density
    scale = Emin + physical.ravel() ** penal * (E0 - Emin)
    K = sparse.coo_matrix(((scale[:, None, None] * ke).ravel(), (rows, cols)),
                          shape=(ndof, ndof)).tocsr()
    K = (K + K.T) * .5
    U[:] = 0.0; U[free] = spsolve(K[free][:, free], force[free])
    relative_residual = float(np.linalg.norm((K @ U - force)[free]) /
                              max(np.linalg.norm(force[free]), 1e-12))
    ue = U[edof]
    ce = np.einsum("ei,ij,ej->e", ue, ke, ue)
    compliance = float(np.sum(scale * ce))
    spec = {**task, "nelx": nx, "nely": ny, "nelz": nz, "volfrac": volfrac,
            "max_iter": max_iter, "min_iter": min_iter, "bc_type": canonical_case,
            "controller": controller,
            "projection": "heaviside_projection" if projected else "none"}
    result = build_result(task_spec=spec, status=status, compliance=compliance,
                        xPhys=physical, U=U, history=history, iterations=len(history),
                        final_change=change, relative_residual=relative_residual,
                        solve_time=time.time() - start, backend="python3d", density_design=density)
    target_beta = beta_max if controller == "periodic_controller" and projected else beta
    result["solver"]["target_beta"] = target_beta
    result["solver"]["continuation_complete"] = final_beta >= target_beta
    return result
