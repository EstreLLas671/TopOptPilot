"""
研究主管 (Research Lead)

职责：任务分解、进度监控、终止决策
输入：科研目标、当前状态、迭代历史、计算预算
输出：任务分解指令、终止决策
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ResearchGoal:
    """科研目标数据模型"""
    task_id: str
    description: str
    geometry_path: Optional[str] = None
    material: Optional[dict] = None
    load_cases: list = field(default_factory=list)
    volume_fraction: float = 0.40
    requirements: dict = field(default_factory=lambda: {
        "connected_components": 1,
        "gray_ratio_max": 0.05,
        "compliance_increase_max": 0.03
    })
    compute_budget: dict = field(default_factory=lambda: {
        "gpu": "RTX 5090",
        "max_runs": 30
    })


@dataclass
class TaskDecomposition:
    """任务分解结果"""
    phases: list = field(default_factory=list)
    estimated_runs: int = 0
    priority: str = "normal"  # high / normal / exploratory


class ResearchLead:
    """
    研究主管负责：
    - 解析科研任务包，验证完整性
    - 决定下一轮应该聚焦什么
    - 判断何时应该终止研究
    """

    def __init__(self, model_client=None):
        self.client = model_client  # PiAgent runtime client

    def validate_task_package(self, task_package: dict) -> dict:
        """
        验证科研任务包的完整性。
        参照方案 §3.1 输入体系校验规则。

        返回: {valid: bool, missing_fields: list, warnings: list}
        """
        required_fields = [
            "research_goal", "geometry", "material",
            "load_cases", "volume_fraction"
        ]
        missing = [f for f in required_fields if f not in task_package]
        warnings = []

        if missing:
            return {"valid": False, "missing_fields": missing, "warnings": warnings}

        # 检查材料的完整性
        material = task_package.get("material", {})
        for key in ["E_MPa", "nu", "density_kg_m3"]:
            if key not in material:
                warnings.append(f"材料参数缺失: {key}")

        # 检查边界条件
        if "requirements" in task_package:
            reqs = task_package["requirements"]
            if reqs.get("gray_ratio_max", 0) <= 0:
                warnings.append("灰度比例阈值未设置或为0")

        return {"valid": True, "missing_fields": [], "warnings": warnings}

    def decide_next_action(self, state) -> dict:
        """
        基于当前状态决定下一步动作。
        决定可以指向：继续实验、重新挖掘文献、修正假设、终止。

        返回: {action: str, target_state: str, reason: str}
        """
        # 如果预算已耗尽
        if state.runs_remaining <= 0:
            return {
                "action": "terminate",
                "target_state": "conclusion",
                "reason": "计算预算已耗尽"
            }

        # 如果连续无信息增益
        if state.consecutive_no_gain_count >= state.max_no_gain_rounds:
            return {
                "action": "terminate",
                "target_state": "conclusion",
                "reason": f"连续{state.consecutive_no_gain_count}轮无信息增益"
            }

        # 如果超迭代次数
        if state.iteration_count >= state.max_iterations:
            return {
                "action": "terminate",
                "target_state": "conclusion",
                "reason": f"达到最大迭代次数({state.max_iterations})"
            }

        # 正常推进
        return {
            "action": "continue",
            "target_state": "experiment_design",
            "reason": "继续实验迭代"
        }

    def estimate_compute_budget(self, experiment_matrix: list) -> dict:
        """
        估算实验矩阵所需计算量。
        返回: {total_runs: int, estimated_hours: float, feasible: bool}
        """
        total_runs = len(experiment_matrix)
        # 假设每轮平均10分钟（含FEA+灵敏度+更新）
        estimated_hours = total_runs * 10 / 60
        return {
            "total_runs": total_runs,
            "estimated_hours": round(estimated_hours, 1),
            "feasible": total_runs <= 30
        }
