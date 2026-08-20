"""
滤波模块 — 灵敏度滤波 / 密度滤波 / Heaviside 投影

经典 99-line 的灵敏度滤波（check，含边界处理）用预构建的稀疏矩阵 H 精确复现：
    dcn(j,i) = Σ w·dc(k,l) / (Σw · x(j,i))，w = max(0, rmin - dist)

88-line 式密度滤波 + Heaviside 投影用于 "projection=heaviside" 实验组：
    xTilde = H @ x           （归一化卷积，无 /x）
    xPhys  = heaviside(xTilde, beta, eta)
    dc_x   = H @ (dc_xPhys · heaviside'(xTilde))     （链式导数的伴随）

稀疏矩阵 H 仅按 (nelx, nely, rmin) 构建一次，整轮优化复用，性能远优于
Python 嵌套循环（60×30、rmin=3 时单次滤波 ~1ms）。
"""

from __future__ import annotations

import numpy as np
from scipy import sparse


def build_filter_matrix(nelx: int, nely: int, rmin: float) -> sparse.csr_matrix:
    """构建归一化卷积滤波矩阵 H ∈ R^(N×N)（N = nelx*nely）。

    H 的行 = 目标单元 (elx=i, ely=j)，列 = 邻域单元 (elx=k, ely=l)，
    元素 = w = max(0, rmin - ||(i,j)-(k,l)||)，行归一化到 Σw。

    单元索引约定与 FE_solver 一致：idx = elx*nely + ely。
    边界单元只统计域内邻居（与经典 check() 行为一致）。

    H @ v 即归一化加权平均；H @ dc 再除以 x 即经典灵敏度滤波。
    """
    if rmin <= 0:
        raise ValueError(f"滤波半径必须为正: rmin={rmin}")
    fr = int(np.floor(rmin))
    n = nelx * nely
    rows, cols, vals = [], [], []

    for i in range(nelx):          # 目标单元 elx
        for j in range(nely):      # 目标单元 ely
            row = i * nely + j     # 单元索引约定 elx*nely + ely
            for k in range(max(i - fr, 0), min(i + fr + 1, nelx)):
                for l in range(max(j - fr, 0), min(j + fr + 1, nely)):
                    w = max(0.0, rmin - np.hypot(i - k, j - l))
                    if w > 0:
                        rows.append(row)
                        cols.append(k * nely + l)
                        vals.append(w)

    H = sparse.coo_matrix((vals, (rows, cols)), shape=(n, n)).tocsr()
    # 行归一化：每行除以 Σw
    rowsum = np.asarray(H.sum(axis=1)).ravel()
    rowsum[rowsum == 0] = 1.0
    inv = 1.0 / rowsum
    H.data *= np.repeat(inv, np.diff(H.indptr))
    return H


def _flat(x: np.ndarray) -> np.ndarray:
    """(nely, nelx) 密度/灵敏度数组 → elx 主序一维向量。

    H 的列索引 = elx*nely + ely（与 FE_solver 单元编号一致），而数组按
    (nely, nelx) 存储时 C 序展平是 ely 主序；nelx ≠ nely 时两者为置换
    关系，必须用 x.T.ravel()（即 elx 主序）才能与 H 对齐。
    """
    return x.T.ravel()


def _unflat(v: np.ndarray, nelx: int, nely: int) -> np.ndarray:
    """elx 主序一维向量 → (nely, nelx) 数组。"""
    return v.reshape(nelx, nely).T


def sensitivity_filter(dc: np.ndarray, H: sparse.csr_matrix,
                       x: np.ndarray) -> np.ndarray:
    """经典 99-line 灵敏度滤波 check()：dcn = (H @ dc) / x。

    dc: shape (nely, nelx) 灵敏度；x: shape (nely, nelx) 当前密度；
    H: build_filter_matrix 构建的滤波矩阵（elx 主序）。
    """
    nelx, nely = x.shape[1], x.shape[0]
    dcn = _unflat(H @ _flat(dc), nelx, nely)
    return dcn / x


def density_filter(x: np.ndarray, H: sparse.csr_matrix) -> np.ndarray:
    """88-line 式密度滤波：xTilde = H @ x（归一化加权平均，无 /x）。"""
    nelx, nely = x.shape[1], x.shape[0]
    return _unflat(H @ _flat(x), nelx, nely)


def adjoint_sensitivity(dc_xPhys: np.ndarray, H: sparse.csr_matrix) -> np.ndarray:
    """密度滤波的伴随（对设计变量 x 的灵敏度）：dc_x = H.T @ dc_xPhys。

    边界行归一化后 H 并不严格对称，必须显式应用转置。
    """
    nelx, nely = dc_xPhys.shape[1], dc_xPhys.shape[0]
    return _unflat(H.T @ _flat(dc_xPhys), nelx, nely)


def heaviside(x: np.ndarray, beta: float, eta: float = 0.5) -> np.ndarray:
    """Heaviside 平滑投影（88-line 式）。

    xPhys = (tanh(beta·eta) + tanh(beta·(x - eta)))
            / (tanh(beta·eta) + tanh(beta·(1 - eta)))

    beta <= 0 时退化为恒等（返回原值），避免 0/0。
    """
    if beta <= 0:
        return x
    num = np.tanh(beta * eta) + np.tanh(beta * (x - eta))
    den = np.tanh(beta * eta) + np.tanh(beta * (1 - eta))
    return num / den


def heaviside_derivative(x: np.ndarray, beta: float, eta: float = 0.5) -> np.ndarray:
    """Heaviside 投影对 xTilde 的导数（链式导数）。

    dxPhys/dxTilde = beta·(1 - tanh²(beta·(xTilde - eta)))
                     / (tanh(beta·eta) + tanh(beta·(1 - eta)))

    beta <= 0 时退化为全 1（恒等映射的导数为 1）。
    """
    if beta <= 0:
        return np.ones_like(x)
    den = np.tanh(beta * eta) + np.tanh(beta * (1 - eta))
    return beta * (1.0 - np.tanh(beta * (x - eta)) ** 2) / den
