"""Deterministic element Von Mises stress post-processing for Q4 and Hex8 FEM."""

from __future__ import annotations

from itertools import product
from typing import Any

import numpy as np


def _parameter(task: dict[str, Any], name: str, default: float) -> float:
    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    return float(task.get(name, params.get(name, default)))


def stress_unit_metadata(task: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative unit assertion; incomplete chains stay normalized."""
    context = task.get("unit_context") if isinstance(task.get("unit_context"), dict) else {}
    trusted = bool(context.get("trusted")) and str(context.get("stress_unit")) == "MPa"
    return {
        "stress_unit": "MPa" if trusted else "normalized",
        "stress_unit_trusted": trusted,
        "stress_unit_reason": str(context.get("reason") or (
            "载荷、几何、材料或单元尺度的量纲链不完整" if not trusted else "N-mm-MPa 量纲链已确认"
        )),
    }


def von_mises_2d(density: np.ndarray, displacement: np.ndarray, *,
                  penal: float, youngs_modulus: float, poisson_ratio: float) -> np.ndarray:
    """Plane-stress Q4 values using the maximum of four Gauss points."""
    density = np.asarray(density, dtype=float)
    displacement = np.asarray(displacement, dtype=float).ravel()
    if density.ndim != 2:
        raise ValueError("2D stress requires a two-dimensional density field")
    nely, nelx = density.shape
    expected = 2 * (nelx + 1) * (nely + 1)
    if displacement.size != expected:
        raise ValueError(f"2D displacement size {displacement.size} does not match {expected}")
    nu = float(poisson_ratio)
    D = float(youngs_modulus) / (1 - nu * nu) * np.array(
        [[1, nu, 0], [nu, 1, 0], [0, 0, (1 - nu) / 2]], dtype=float
    )
    gauss = (-1 / np.sqrt(3), 1 / np.sqrt(3))
    matrices: list[np.ndarray] = []
    for xi, eta in product(gauss, repeat=2):
        dndx = .5 * np.array([-(1 - eta), 1 - eta, 1 + eta, -(1 + eta)])
        dndy = .5 * np.array([-(1 - xi), -(1 + xi), 1 + xi, 1 - xi])
        B = np.zeros((3, 8))
        for node in range(4):
            col = 2 * node
            B[:, col:col + 2] = [[dndx[node], 0], [0, dndy[node]],
                                  [dndy[node], dndx[node]]]
        matrices.append(B)
    output = np.zeros_like(density)
    for elx in range(nelx):
        for ely in range(nely):
            n1 = (nely + 1) * elx + ely
            n2 = (nely + 1) * (elx + 1) + ely
            edof = np.array([2*n1, 2*n1+1, 2*n2, 2*n2+1,
                             2*n2+2, 2*n2+3, 2*n1+2, 2*n1+3])
            ue = displacement[edof]
            effective = density[ely, elx] ** float(penal)
            values = []
            for B in matrices:
                sigma = effective * D @ B @ ue
                values.append(np.sqrt(sigma[0] ** 2 - sigma[0] * sigma[1]
                                      + sigma[1] ** 2 + 3 * sigma[2] ** 2))
            output[ely, elx] = max(values)
    return output


def _hex8_connectivity(nx: int, ny: int, nz: int) -> np.ndarray:
    def node(i: int, j: int, k: int) -> int:
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


def von_mises_3d(density: np.ndarray, displacement: np.ndarray, *,
                  penal: float, youngs_modulus: float, poisson_ratio: float,
                  minimum_modulus: float = 1e-6) -> np.ndarray:
    """Hex8 values using the maximum of eight Gauss points.

    Python's 3D solver stores fields as (nz, ny, nx), matching its connectivity.
    """
    density = np.asarray(density, dtype=float)
    displacement = np.asarray(displacement, dtype=float).ravel()
    if density.ndim != 3:
        raise ValueError("3D stress requires a three-dimensional density field")
    nz, ny, nx = density.shape
    edof = _hex8_connectivity(nx, ny, nz)
    expected = 3 * (nx + 1) * (ny + 1) * (nz + 1)
    if displacement.size != expected:
        raise ValueError(f"3D displacement size {displacement.size} does not match {expected}")
    E, nu = float(youngs_modulus), float(poisson_ratio)
    factor = E / ((1 + nu) * (1 - 2 * nu))
    D = factor * np.array([
        [1-nu, nu, nu, 0, 0, 0], [nu, 1-nu, nu, 0, 0, 0],
        [nu, nu, 1-nu, 0, 0, 0], [0, 0, 0, (1-2*nu)/2, 0, 0],
        [0, 0, 0, 0, (1-2*nu)/2, 0], [0, 0, 0, 0, 0, (1-2*nu)/2],
    ], dtype=float)
    signs = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                      [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=float)
    matrices: list[np.ndarray] = []
    gauss = (-1 / np.sqrt(3), 1 / np.sqrt(3))
    for xi, eta, zeta in product(gauss, repeat=3):
        B = np.zeros((6, 24))
        for node, (sx, sy, sz) in enumerate(signs):
            dnx = sx * (1 + sy * eta) * (1 + sz * zeta) / 4
            dny = sy * (1 + sx * xi) * (1 + sz * zeta) / 4
            dnz = sz * (1 + sx * xi) * (1 + sy * eta) / 4
            col = 3 * node
            B[:, col:col + 3] = [[dnx, 0, 0], [0, dny, 0], [0, 0, dnz],
                                  [dny, dnx, 0], [0, dnz, dny], [dnz, 0, dnx]]
        matrices.append(B)
    output = np.zeros(density.size)
    flat_density = density.ravel()
    for index, element_dofs in enumerate(edof):
        effective = minimum_modulus + (1 - minimum_modulus) * flat_density[index] ** float(penal)
        ue = displacement[element_dofs]
        values = []
        for B in matrices:
            sigma = effective * D @ B @ ue
            values.append(np.sqrt(.5 * ((sigma[0]-sigma[1])**2 + (sigma[1]-sigma[2])**2
                                        + (sigma[2]-sigma[0])**2)
                                  + 3 * (sigma[3]**2 + sigma[4]**2 + sigma[5]**2)))
        output[index] = max(values)
    return output.reshape(density.shape)


def compute_von_mises(task: dict[str, Any], density: np.ndarray,
                      displacement: np.ndarray, history: list[dict[str, Any]]) -> np.ndarray:
    penal = float(history[-1].get("penal")) if history and history[-1].get("penal") is not None else _parameter(task, "penal", _parameter(task, "p_start", 3.0))
    E = _parameter(task, "E", 1.0)
    nu = _parameter(task, "nu", 0.3)
    if np.asarray(density).ndim == 2:
        return von_mises_2d(density, displacement, penal=penal,
                            youngs_modulus=E, poisson_ratio=nu)
    if np.asarray(density).ndim == 3:
        return von_mises_3d(density, displacement, penal=penal,
                            youngs_modulus=E, poisson_ratio=nu)
    raise ValueError("Stress post-processing supports only 2D and 3D fields")
