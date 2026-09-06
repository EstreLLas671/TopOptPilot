"""
审稿Agent (Review Agent)

职责：从新颖性、物理自洽性、可证伪性和计算成本四方面评审候选假设
输入：候选假设 + 相关证据
输出：评审计分、反例分析、排序
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ReviewScore:
    """四维评审打分"""
    novelty: float = 0.0       # 新颖性 (0-10)
    physical_consistency: float = 0.0  # 物理自洽性 (0-10)
    falsifiability: float = 0.0  # 可证伪性 (0-10)
    compute_cost: float = 0.0  # 计算成本可接受度 (0-10, 越高越可接受)

    @property
    def total(self) -> float:
        return (self.novelty + self.physical_consistency +
                self.falsifiability + self.compute_cost)


@dataclass
class CounterExample:
    """反例分析"""
    hypothesis_id: str
    scenario: str  # 可能失败的具体场景
    physical_reason: str  # 物理解释
    severity: str = "medium"  # high / medium / low


@dataclass
class ReviewResult:
    """评审结果"""
    hypothesis_id: str
    scores: ReviewScore
    counter_examples: list[CounterExample] = field(default_factory=list)
    summary: str = ""
    rank: int = 0


class ReviewAgent:
    """
    审稿Agent负责：
    - 从四维角度评审假设质量
    - 生成反例（指出潜在失败模式）
    - 排序候选假设
    - 禁止：不得用自评分代替真实实验
    """

    def __init__(self, model_client=None):
        self.client = model_client

    def review_hypotheses(self, hypotheses_set) -> list[ReviewResult]:
        """评审所有候选假设，返回排序结果"""
        results = []

        for h in hypotheses_set.hypotheses:
            scores = self._evaluate_hypothesis(h)
            counter_exs = self._generate_counter_examples(h)

            results.append(ReviewResult(
                hypothesis_id=h.id,
                scores=scores,
                counter_examples=counter_exs,
                summary=self._summarize_review(h, scores, counter_exs)
            ))

        # 按总分排序
        results.sort(key=lambda r: r.scores.total, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        return results

    def _evaluate_hypothesis(self, h) -> ReviewScore:
        """对单个假设进行四维评审"""
        scores = ReviewScore()

        # 新颖性：是否已有研究证明
        if "已有" in h.statement or "已知" in h.statement:
            scores.novelty = 4.0
        elif "联合反馈" in h.statement:
            scores.novelty = 8.5
        else:
            scores.novelty = 6.0

        # 物理自洽性：是否与拓扑优化基本理论一致
        if any(term in h.statement for term in ["灰度", "柔度", "连通", "刚度"]):
            scores.physical_consistency = 7.0
        elif "固定调度" in h.statement:
            scores.physical_consistency = 8.0
        else:
            scores.physical_consistency = 5.0

        # 可证伪性：是否存在明确判断标准
        if h.success_conditions and h.failure_conditions:
            scores.falsifiability = 9.0
        else:
            scores.falsifiability = 4.0

        # 计算成本
        budget = h.compute_budget_estimate
        if budget <= 5:
            scores.compute_cost = 9.0
        elif budget <= 10:
            scores.compute_cost = 7.0
        else:
            scores.compute_cost = 4.0

        return scores

    def _generate_counter_examples(self, h) -> list[CounterExample]:
        """反例生成（参照方案 §7.1 审稿Agent职责）"""
        examples = []

        if "联合反馈" in h.statement:
            examples.append(CounterExample(
                hypothesis_id=h.id,
                scenario="粗网格或载荷剧烈变化时，多指标间的权重竞争可能导致控制策略振荡",
                physical_reason="多个反馈信号的相位差可能导致控制器在参数空间中震荡，"
                               "反而增加了达到收敛所需的迭代次数",
                severity="medium"
            ))
            examples.append(CounterExample(
                hypothesis_id=h.id,
                scenario="在高对比刚度下（SIMP惩罚后期），连通性指标可能主导其他指标",
                physical_reason="连通性下降迫使控制器回退参数，"
                               "但回退后柔度可能已经不可逆地增加",
                severity="high"
            ))

        elif "单一灰度反馈" in h.statement:
            examples.append(CounterExample(
                hypothesis_id=h.id,
                scenario="灰度比例保持在阈值以下，但柔度持续增加（灰度低≠结构优）",
                physical_reason="灰度只反映0-1清晰度，不反映力学效率。"
                               "低灰度但高柔度的结构是可能的",
                severity="high"
            ))

        elif "固定调度" in h.statement:
            examples.append(CounterExample(
                hypothesis_id=h.id,
                scenario="细网格或复杂载荷下，固定调度可能错过最佳参数窗口",
                physical_reason="不同分辨率下最优参数路径不同，"
                               "一套固定的β增长曲线无法适应所有场景",
                severity="medium"
            ))

        return examples

    def _summarize_review(self, h, scores, counter_exs) -> str:
        """生成评审摘要"""
        hid = getattr(h, 'hypothesis_id', None) or getattr(h, 'id', '?')
        risks = ", ".join(f"{c.scenario}[{c.severity}]" for c in counter_exs[:2])
        return (
            f"H{hid[-1] if len(str(hid)) > 1 else hid}:"
            f"新颖性{scores.novelty}/10, "
            f"物理自洽{scores.physical_consistency}/10, "
            f"可证伪{scores.falsifiability}/10, "
            f"成本{scores.compute_cost}/10. "
            f"总分{scores.total}/40. "
            f"风险: {risks}"
        )