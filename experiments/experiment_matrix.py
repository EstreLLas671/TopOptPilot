"""
实验矩阵设计工具

参照方案 §9.4 核心实验矩阵设计：

实验组  插件组合                          回答的问题
B0      OC + PDE滤波 + 无投影 + 固定p     无延续基线表现
B1      OC + PDE + 固定轮次β延续          人工固定调度
A1      OC + PDE + 灰度反馈β              单一灰度指标
A2      OC + PDE + 收敛反馈β/p            柔度稳定性
Ours    灰度+柔度+连通+求解难度联合反馈    核心假设
Ablation 逐项移除四类反馈                 每个信息源贡献
"""

import itertools
from dataclasses import dataclass, field


@dataclass
class ExperimentGroup:
    """实验组定义"""
    group_id: str
    description: str
    hypotheses: list = field(default_factory=list)
    controller: str = ""
    params: dict = field(default_factory=dict)


# 预定义实验组（参照方案 §9.4）
EXPERIMENT_GROUPS = [
    ExperimentGroup(
        group_id="B0",
        description="无延续基线：OC + PDE滤波 + 无投影 + 固定p=3",
        hypotheses=["H0_null"],
        controller="fixed_controller",
        params={"p": 3, "beta": 1, "filter_radius": 1.5}
    ),
    ExperimentGroup(
        group_id="B1",
        description="固定轮次延续：OC + PDE + Heaviside + 每10步β+=2",
        hypotheses=["H3"],
        controller="periodic_controller",
        params={"p_start": 3, "beta_schedule": "linear", "beta_step": 2, "beta_interval": 10}
    ),
    ExperimentGroup(
        group_id="A1",
        description="灰度反馈：OC + PDE + Heaviside + 灰度比例驱动β调整",
        hypotheses=["H2"],
        controller="gray_feedback_controller",
        params={"beta_max": 16, "p_start": 3, "gray_threshold": 0.05}
    ),
    ExperimentGroup(
        group_id="A2",
        description="收敛反馈：OC + PDE + Heaviside + 柔度稳定性驱动β/p",
        hypotheses=["H2_v2"],
        controller="convergence_feedback_controller",
        params={"beta_max": 16, "p_start": 3, "oscillation_threshold": 0.03}
    ),
    ExperimentGroup(
        group_id="Ours",
        description="联合反馈：灰度+柔度+连通+求解难度四指标联合",
        hypotheses=["H1"],
        controller="joint_feedback_controller",
        params={"beta_max": 16, "p_start": 3,
                "feedback_weights": [0.4, 0.3, 0.2, 0.1]}
    ),
    ExperimentGroup(
        group_id="Ablation",
        description="消融：逐项移除反馈信号（4组子实验）",
        hypotheses=["H1_ablation_gray", "H1_ablation_compliance",
                    "H1_ablation_connectivity", "H1_ablation_solver"],
        controller="joint_feedback_controller",
        params={"ablation_mode": "sequential"}
    ),
]


def build_experiment_matrix(groups: list = None,
                            load_cases: list = None,
                            mesh_levels: list = None) -> list:
    """
    构建完整实验矩阵。

    返回: [(group_id, load_case, mesh_level, controller, params), ...]
    """
    groups = groups or EXPERIMENT_GROUPS
    load_cases = load_cases or ["vertical", "lateral"]
    mesh_levels = mesh_levels or ["coarse", "medium", "fine"]

    matrix = []
    for g in groups:
        for load, mesh in itertools.product(load_cases, mesh_levels):
            matrix.append({
                "group_id": g.group_id,
                "description": g.description,
                "load_case": load,
                "mesh_level": mesh,
                "controller": g.controller,
                "params": {
                    **g.params,
                    "load_case": load,
                    "mesh_level": mesh
                }
            })
    return matrix