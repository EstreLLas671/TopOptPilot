"""
假设Agent (Hypothesis Agent)

职责：生成 3～5 个可证伪候选假设
输入：知识缺口列表、场景信息、历史实验数据
输出：候选假设列表（每个包含完整假设陈述、成功/失败条件、基线、指标、计算预算）
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CandidateHypothesis:
    """候选假设（参照方案 §1.3 核心科学问题格式）"""
    id: str
    title: str
    statement: str  # 完整假设陈述
    reasoning_chain: list  # 推导链

    # 成功与失败条件
    success_conditions: dict = field(default_factory=dict)
    failure_conditions: dict = field(default_factory=dict)

    # 实验设计
    baseline: str = ""  # 对照基线方案
    metrics: list = field(default_factory=list)
    required_plugins: list = field(default_factory=list)
    compute_budget_estimate: int = 5  # 预估所需run次数

    # 论文证据支撑
    supporting_evidence: list = field(default_factory=list)
    counter_evidence: list = field(default_factory=list)

    # 状态
    status: str = "proposed"  # proposed / reviewed / in_experiment / supported / rejected / insufficient

    # 假设推导过程
    derivation: str = ""


@dataclass
class HypothesisSet:
    """假设集合"""
    hypotheses: list[CandidateHypothesis] = field(default_factory=list)
    research_goal: str = ""
    constraints: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.hypotheses)

    def add(self, hypothesis: CandidateHypothesis):
        self.hypotheses.append(hypothesis)

    def get_by_id(self, hid: str) -> Optional[CandidateHypothesis]:
        for h in self.hypotheses:
            if h.id == hid:
                return h
        return None


class HypothesisAgent:
    """
    假设Agent负责：
    - 根据知识缺口、场景和历史生成候选假设
    - 每个假设必须有可量化的成功/失败条件
    - 必须包含基线、指标和计算预算
    """

    def __init__(self, model_client=None):
        self.client = model_client

    def generate_hypotheses(self, knowledge_gaps: list, research_goal: dict,
                            historical_results: list = None) -> HypothesisSet:
        """
        从知识缺口生成 3～5 个候选假设。
        参照方案 §1.3 的核心科学问题结构。
        """
        hs = HypothesisSet(research_goal=research_goal.get("description", ""))

        # 建议生成三个候选：
        hs.add(self._create_hypothesis_H1())
        hs.add(self._create_hypothesis_H2())
        hs.add(self._create_hypothesis_H3())

        return hs

    def _create_hypothesis_H1(self) -> CandidateHypothesis:
        """
        核心假设H1：联合反馈控制器
        参照方案 §1.3
        """
        return CandidateHypothesis(
            id="H1",
            title="联合反馈控制器优于固定调度",
            statement=(
                "基于灰度比例、柔度振荡、连通性和线性求解难度的联合反馈控制器，"
                "相比固定调度，能够在相同体积分数下将灰度比例降低至预设阈值，"
                "同时把最终柔度增幅控制在允许范围，并减少达到收敛所需的迭代次数。"
            ),
            reasoning_chain=[
                "1. 固定调度在所有迭代中保持相同的惩罚或投影参数",
                "2. 不同结构、载荷和网格下最优调度不同",
                "3. 联合反馈利用四个正交指标（灰度、柔度稳定、连通、求解难度）",
                "4. 控制器根据实时状态动态调整参数",
                "5. 预期：适应性优于固定调度"
            ],
            success_conditions={
                "gray_ratio_below": 0.05,
                "compliance_increase_within": 0.03,
                "connected_components": 1,
                "iteration_reduction": "significant"
            },
            failure_conditions={
                "gray_ratio_above": 0.10,
                "compliance_increase_above": 0.08,
                "disconnected": True
            },
            baseline="OC + PDE滤波 + 无投影 + 固定p=3",
            metrics=["gray_ratio", "compliance", "connected_components",
                     "cg_iterations", "solve_time"],
            required_plugins=["OC", "PDE_filter", "Heaviside_projection",
                              "joint_feedback_controller"],
            compute_budget_estimate=8,
            supporting_evidence=[],
            counter_evidence=[],
            derivation=(
                "基于灰度比例过高、柔度振荡、连通性丢失和线性求解难度增加四个独立信号，"
                "设计联合反馈控制器动态调整投影陡峭度β和SIMP惩罚指数p。"
                "四组实验中，每组在粗/中/细三档网格和两个载荷工况下测试。"
            )
        )

    def _create_hypothesis_H2(self) -> CandidateHypothesis:
        """
        候选假设H2：单一灰度反馈的有效性
        """
        return CandidateHypothesis(
            id="H2",
            title="单一灰度反馈足以有效控制投影",
            statement=(
                "仅基于灰度比例的单指标反馈控制器，在大部分3D支架拓扑优化场景中，"
                "可以达到与联合反馈相近的灰度控制效果，但可能在柔度稳定性上不足。"
            ),
            reasoning_chain=[
                "1. 灰度比例是0-1清晰度的最直接指标",
                "2. 单指标控制更简单、可解释性更强",
                "3. 但缺少柔度稳定性反馈可能导致过早收敛到局部最优"
            ],
            success_conditions={
                "gray_ratio_below": 0.05,
                "compliance_increase_within": 0.05,
            },
            failure_conditions={
                "compliance_increase_above": 0.10,
                "premature_convergence": True
            },
            baseline="OC + PDE滤波 + 无投影 + 固定p=3",
            metrics=["gray_ratio", "compliance", "cg_iterations"],
            required_plugins=["OC", "PDE_filter", "Heaviside_projection",
                              "gray_feedback_controller"],
            compute_budget_estimate=6,
            supporting_evidence=[],
            counter_evidence=[],
            derivation="消融实验：从联合反馈中移除柔度/连通/求解难度信号，观察退化程度。"
        )

    def _create_hypothesis_H3(self) -> CandidateHypothesis:
        """
        候选假设H3：固定调度在特定场景中的稳健性
        """
        return CandidateHypothesis(
            id="H3",
            title="精心设计的固定调度在粗网格上优于自适应方法",
            statement=(
                "在粗网格或计算预算有限时，预先设计的固定参数调度（如线性增长β）"
                "比自适应反馈控制器更稳健，因为自适应方法需要额外的迭代来探索参数空间。"
            ),
            reasoning_chain=[
                "1. 粗网格上灰度指标本身的区分度有限",
                "2. 自适应控制器需要多次迭代才能收敛参数",
                "3. 固定调度没有探索成本，直接使用已知有效路径"
            ],
            success_conditions={
                "performance_on_coarse_grid": "fixed_scheduling_better",
                "total_time_less": True
            },
            failure_conditions={
                "performance_on_fine_grid": "adaptive_better_significantly",
                "gray_ratio_above": 0.15
            },
            baseline="联合反馈控制器",
            metrics=["compliance", "total_time", "gray_ratio"],
            required_plugins=["OC", "PDE_filter", "Heaviside_projection",
                              "periodic_controller"],
            compute_budget_estimate=6,
            supporting_evidence=[],
            counter_evidence=[],
            derivation=(
                "跨网格稳健性测试：在粗（50K单元）、中（200K）、细（500K+）三档网格上"
                "分别比较固定调度与联合反馈的性能差异。"
            )
        )