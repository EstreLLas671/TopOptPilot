"""
FE 求解器 — `求解器模块/FE_solver.m` 的 Python (numpy/scipy) 移植

与 MATLAB 版本逐行语义一致：
  1. 计算单元刚度矩阵 KE（四节点四边形单元 8×8）
  2. SIMP 组装全局刚度矩阵 K = Σ x^penal * KE
  3. 按 bc_type 施加边界条件（MBB / cantilever / L-bracket /
     simply_supported / custom）
  4. 求解 K·U = F（稀疏直接求解），返回位移场、柔度与相对残差

密度场 x 的索引约定与 .m 一致：x(ely, elx)，形状 (nely, nelx)。
自由度编号 0 起（与 .m 的 1 起编号相差 1）。
"""

from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.sparse.linalg import spsolve


def lk_matrix(E: float = 1.0, nu: float = 0.3) -> np.ndarray:
    """8×8 单元刚度矩阵（与 FE_solver.m 中 lk_matrix 完全一致）"""
    k = np.array([
        1/2 - nu/6,      1/8 + nu/8,     -1/4 - nu/12,  -1/8 + 3*nu/8,
        -1/4 + nu/12,    -1/8 - nu/8,     nu/6,          1/8 - 3*nu/8,
    ])
    return E / (1 - nu**2) * np.array([
        [k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7]],
        [k[1], k[0], k[7], k[6], k[5], k[4], k[3], k[2]],
        [k[2], k[7], k[0], k[5], k[6], k[3], k[4], k[1]],
        [k[3], k[6], k[5], k[0], k[7], k[2], k[1], k[4]],
        [k[4], k[5], k[6], k[7], k[0], k[1], k[2], k[3]],
        [k[5], k[4], k[3], k[2], k[1], k[0], k[7], k[6]],
        [k[6], k[3], k[4], k[1], k[2], k[7], k[0], k[5]],
        [k[7], k[2], k[1], k[4], k[3], k[6], k[5], k[0]],
    ])


class FESolver:
    """2D 四边形单元 FEM 求解器（Python 移植 FE_solver.m）"""

    def __init__(self, nelx: int, nely: int, E: float = 1.0, nu: float = 0.3):
        if nelx <= 0 or nely <= 0:
            raise ValueError(f"网格尺寸必须为正: nelx={nelx}, nely={nely}")
        self.nelx = nelx
        self.nely = nely
        self.E = E
        self.nu = nu
        self.ndof = 2 * (nelx + 1) * (nely + 1)
        self.KE = lk_matrix(E, nu)
        # 预计算每个单元的 8 个自由度编号（0 起），与 .m 的 edof 顺序一致
        self.edof_mat = self._build_edof_mat(nelx, nely)

    @staticmethod
    def _build_edof_mat(nelx: int, nely: int) -> np.ndarray:
        """(nelx*nely, 8) 的单元自由度编号矩阵。

        行顺序 elx 外层、ely 内层（与 FE_solver.m 组装循环一致）；
        单元节点顺序 (左下, 右下, 右上, 左上)，与 KE 行/列对应。
        """
        edof_mat = np.zeros((nelx * nely, 8), dtype=int)
        for elx in range(nelx):
            for ely in range(nely):
                n1 = (nely + 1) * elx + ely          # 左下节点 (0 起)
                n2 = (nely + 1) * (elx + 1) + ely    # 右下节点 (0 起)
                edof_mat[elx * nely + ely, :] = [
                    2 * n1, 2 * n1 + 1,     # 左下 (x, y)
                    2 * n2, 2 * n2 + 1,     # 右下 (x, y)
                    2 * n2 + 2, 2 * n2 + 3, # 右上 (x, y)
                    2 * n1 + 2, 2 * n1 + 3, # 左上 (x, y)
                ]
        return edof_mat

    def assemble(self, x: np.ndarray, penal: float) -> sparse.csr_matrix:
        """SIMP 组装全局刚度矩阵 K = Σ x^penal * KE。

        x: shape (nely, nelx)，密度场。
        """
        if x.shape != (self.nely, self.nelx):
            raise ValueError(
                f"密度场形状应为 {(self.nely, self.nelx)}，实际 {x.shape}")
        if penal < 0:
            raise ValueError(f"惩罚指数不能为负: penal={penal}")

        n_elems = self.nelx * self.nely
        # 每个单元按 SIMP 插值缩放的 KE
        Ke_mat = (x.T.ravel() ** penal)[:, None, None] * self.KE
        # 64 个 (i, j, s) 三元组：i 行 = edof[e] 每列重复 8 次 → i=e[A]
        i_block = np.repeat(self.edof_mat, 8, axis=1)   # (n_elems, 64)
        # j 行 = edof[e] 整体平铺 8 次 → j=e[B]
        j_block = np.tile(self.edof_mat, (1, 8))        # (n_elems, 64)
        # s 行 = Ke[e] 展平 → s=e[A,B]
        s_block = Ke_mat.reshape(n_elems, 64)

        K = sparse.coo_matrix(
            (s_block.ravel(), (i_block.ravel(), j_block.ravel())),
            shape=(self.ndof, self.ndof),
        ).tocsr()
        return K

    def apply_bc(self, bc_type: str, bc_config: dict = None,
                 x: np.ndarray = None) -> tuple[np.ndarray, np.ndarray]:
        """施加边界条件，返回 (fixeddofs, F)。

        bc_type: MBB / cantilever / L-bracket / simply_supported / custom
        bc_config: 供 custom 使用，遵循 FE_solver.m 的约定：
            - loads:     [n×3] 每行 [节点号(1起), 方向(1=x,2=y), 力值]
            - fixeddofs: [1×m] 固定自由度编号列表 (1起)
        x: 可选，仅 L-bracket 情形下用于将左上角区域固定为极小密度
           （非设计域）——本函数不修改 x，只施加标准载荷/约束。

        返回 0 起索引的 fixeddofs 与载荷向量 F（长度 ndof）。
        """
        nelx, nely = self.nelx, self.nely
        ndof = self.ndof
        F = np.zeros(ndof, dtype=float)
        bc_config = bc_config or {}

        if bc_type == "MBB":
            # 左边界 x 方向全部固定（对称面）：自由度 0,2,4,...,2*nely
            fixeddofs = np.arange(0, 2 * (nely + 1), 2, dtype=int)
            # 右下角 y 固定：全局最后一个自由度
            fixeddofs = np.union1d(fixeddofs, np.array([ndof - 1]))
            # 左上角节点(0起)的 y 自由度 = 1，向下单位力
            F[1] = -1.0

        elif bc_type == "cantilever":
            # 左边界全部自由度固定：0..2*(nely+1)-1
            fixeddofs = np.arange(0, 2 * (nely + 1), dtype=int)
            # 右下角 y 自由度 = ndof-1，向下单位力
            F[ndof - 1] = -1.0

        elif bc_type == "L-bracket":
            # 顶部边界全部节点 x、y 固定
            fixeddofs = []
            for i in range(nelx + 1):
                node_top = (nely + 1) * i + nely   # 第 i+1 列顶部节点 (0起)
                fixeddofs.extend([2 * node_top, 2 * node_top + 1])
            fixeddofs = np.array(sorted(set(fixeddofs)), dtype=int)
            # 右侧边中点：x 方向向右单位力
            # .m 中为 1 起 (nely+1)*nelx + ceil((nely+1)/2)，转 0 起 = nely//2
            right_mid_node = (nely + 1) * nelx + nely // 2
            F[2 * right_mid_node] = 1.0

        elif bc_type == "simply_supported":
            # 左下角 x、y 都固定；右下角 y 固定
            fixeddofs = np.array([0, 1, ndof - 1], dtype=int)
            # 顶部中点 y 方向向下单位力
            top_mid_node = (nely + 1) * round(nelx / 2) + nely
            F[2 * top_mid_node + 1] = -1.0

        elif bc_type == "custom":
            # 完全自定义：bc_config.fixeddofs / bc_config.loads（1 起编号）
            fixeddofs = np.asarray(bc_config.get("fixeddofs", []), dtype=int) - 1
            fixeddofs = np.sort(np.unique(fixeddofs))
            loads = np.asarray(bc_config.get("loads", []), dtype=float)
            if loads.ndim == 1:
                loads = loads.reshape(1, -1)
            for row in loads:
                node_id, dof_dir, force_val = int(row[0]), int(row[1]), row[2]
                dof_idx = 2 * (node_id - 1) + (dof_dir - 1)   # 0 起
                F[dof_idx] += force_val

        else:
            raise ValueError(
                f"未知的边界条件类型: {bc_type}。支持: MBB, cantilever, "
                f"L-bracket, simply_supported, custom")

        return fixeddofs, F

    def solve(self, x: np.ndarray, penal: float, bc_type: str,
              bc_config: dict = None) -> dict:
        """完整求解：组装 → 施加 BC → 解 K·U=F。

        返回: {
            "U":               位移场 (ndof,)，固定自由度处为 0
            "compliance":      柔度 C = F^T·U（标量）
            "relative_residual": ||K U - F|| / ||F||（自由自由度上）
            "fixeddofs":       0 起索引
            "freedofs":        0 起索引
            "F":               载荷向量
        }
        """
        K = self.assemble(x, penal)
        fixeddofs, F = self.apply_bc(bc_type, bc_config)
        alldofs = np.arange(self.ndof)
        freedofs = np.setdiff1d(alldofs, fixeddofs)

        U = np.zeros(self.ndof)
        if freedofs.size:
            Kff = K[freedofs][:, freedofs]
            U[freedofs] = spsolve(Kff, F[freedofs])

        compliance = float(F @ U)
        # 相对残差（自由自由度上），直接求解应接近机器精度
        if np.linalg.norm(F[freedofs]) > 0:
            residual = float(np.linalg.norm(
                K[freedofs][:, freedofs] @ U[freedofs] - F[freedofs])
                / np.linalg.norm(F[freedofs]))
        else:
            residual = 0.0

        return {
            "U": U,
            "compliance": compliance,
            "relative_residual": residual,
            "fixeddofs": fixeddofs,
            "freedofs": freedofs,
            "F": F,
        }

    def element_compliance(self, U: np.ndarray, penal: float) -> np.ndarray:
        """逐单元柔度 C_e = ue^T·KE·ue，用于灵敏度计算。

        返回 shape (nely, nelx)。单元索引 k = elx*nely + ely（ely 为快速
        索引，与组装一致），因此需 reshape(nelx, nely).T 回到 (ely, elx)。
        """
        Ue = U[self.edof_mat]                     # (n_elems, 8)
        ce = np.einsum("ij,jk,ik->i", Ue, self.KE, Ue)
        return ce.reshape(self.nelx, self.nely).T


def compute_sensitivities(xPhys: np.ndarray, U: np.ndarray, penal: float,
                          KE: np.ndarray, nelx: int, nely: int) -> np.ndarray:
    """柔顺度灵敏度：dc = -penal * xPhys^(penal-1) * ue^T·KE·ue。

    xPhys: shape (nely, nelx)，物理密度场
    U:     位移场
    KE:    8×8 单元刚度矩阵
    返回 shape (nely, nelx)，最小化问题下通常为负。
    """
    edof_mat = FESolver._build_edof_mat(nelx, nely)
    Ue = U[edof_mat]                              # (n_elems, 8)
    # 逐单元: ce[i] = ue_i^T · KE · ue_i
    ce = np.einsum("ij,jk,ik->i", Ue, KE, Ue)
    # 单元索引 k = elx*nely + ely → reshape(nelx, nely).T 回到 (ely, elx)
    ce = ce.reshape(nelx, nely).T
    dc = -penal * (xPhys ** (penal - 1)) * ce
    return dc
