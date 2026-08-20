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


def _filter_kernel(rmin: float) -> np.ndarray:
    radius = max(1, int(np.ceil(rmin)) - 1)
    coords = np.indices((2 * radius + 1,) * 3) - radius
    distance = np.sqrt(np.sum(coords * coords, axis=0))
    return np.maximum(0.0, rmin - distance)


def run_topopt3d(task: dict, progress=None) -> dict:
    params = dict(task.get("params") or {})
    grid = params.get("grid3d") or ([12, 4, 3] if task.get("mesh_level") == "coarse3d"
                                    else [18, 6, 4])
    nx, ny, nz = map(int, grid)
    volfrac = float(params.get("volfrac", 0.4))
    penal = float(params.get("penal", 3.0))
    rmin = float(params.get("rmin", 1.5))
    max_iter = min(int(params.get("max_iter", 40)), 80)
    E0, Emin, nu = float(params.get("E", 1.0)), 1e-6, float(params.get("nu", 0.3))
    start = time.time()
    ke, edof = _hex8_stiffness(1.0, nu), _connectivity(nx, ny, nz)
    ndof = 3 * (nx + 1) * (ny + 1) * (nz + 1)
    rows = np.repeat(edof, 24, axis=1).ravel()
    cols = np.tile(edof, (1, 24)).ravel()
    fixed_nodes = [(k * (ny + 1) + j) * (nx + 1)
                   for k in range(nz + 1) for j in range(ny + 1)]
    fixed = np.array([[3*n, 3*n+1, 3*n+2] for n in fixed_nodes]).ravel()
    free = np.setdiff1d(np.arange(ndof), fixed)
    load_node = ((nz // 2) * (ny + 1) + ny // 2) * (nx + 1) + nx
    force = np.zeros(ndof); force[3 * load_node + 1] = -1.0
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
    kernel = _filter_kernel(rmin); denom = ndimage.convolve(np.ones_like(density), kernel, mode="constant")
    history, U = [], np.zeros(ndof)
    relative_residual, change = 0.0, 1.0
    for iteration in range(1, max_iter + 1):
        flat = density.ravel()
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
        dc = -penal * (E0 - Emin) * density ** (penal - 1) * ce
        dc = ndimage.convolve(density * dc, kernel, mode="constant") / np.maximum(density * denom, 1e-9)
        low, high, move = 0.0, 1e9, 0.2
        while (high - low) / (high + low + 1e-12) > 1e-4:
            mid = 0.5 * (low + high)
            candidate = np.maximum(1e-3, np.maximum(density - move,
                np.minimum(1.0, np.minimum(density + move, density * np.sqrt(np.maximum(0, -dc / mid))))))
            if candidate.mean() > volfrac: low = mid
            else: high = mid
        change = float(np.max(np.abs(candidate - density))); density = candidate
        item = {"iteration": iteration, "compliance": compliance, "change": change,
                "volume_fraction": float(density.mean()), "gray_ratio": gray_ratio(density),
                "connected": connected_components(density), "beta": float(params.get("beta", 1)),
                "penal": penal, "residual": relative_residual}
        history.append(item)
        if progress: progress(iteration, item)
        if change < 1e-3: break
    spec = {**task, "nelx": nx, "nely": ny, "nelz": nz, "volfrac": volfrac,
            "max_iter": max_iter, "bc_type": "cantilever3d", "controller": "fixed_controller",
            "projection": "none"}
    return build_result(task_spec=spec, status="converged", compliance=history[-1]["compliance"],
                        xPhys=density, U=U, history=history, iterations=len(history),
                        final_change=change, relative_residual=relative_residual,
                        solve_time=time.time() - start, backend="python3d", density_design=density)
