"""
审计Agent (Audit Agent)

职责：读取数值结果和图像，判断结论等级，决定下一轮动作
输入：实验结果（数值、曲线、日志）、原始假设
输出：结论等级、诊断分析、下一轮建议
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class VerdictLevel(Enum):
    """结论等级（参照方案 §8.2）"""
    SUPPORTED = "supported"              # 证据支持假设
    PARTIALLY_SUPPORTED = "partially_supported"  # 部分支持，有适用边界
    NOT_SUPPORTED = "not_supported"      # 不支持，假设被否定
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"  # 证据不足


@dataclass
class ExperimentResult:
    """单个实验结果"""
    run_id: str
    task_id: str
    status: str  # converged / failed / timeout
    objective: dict  # {compliance: float}
    constraints: dict  # {volume_fraction: float}
    quality: dict  # {gray_ratio, connected_components, max_displacement}
    solver: dict  # {backend, relative_residual, cg_iterations, solve_time}
    artifacts: dict  # {density, history, log}
    hypothesis_id: str = ""
    experiment_group: str = ""


@dataclass
class AuditVerdict:
    """审计裁决"""
    hypothesis_id: str
    level: VerdictLevel
    evidence_summary: str
    diagnostics: list = field(default_factory=list)
    applicability_boundary: str = ""  # 适用边界描述
    next_action: str = ""  # continue / reiterate / stop
    confidence: float = 0.0  # 置信度


class ResultAnalyzer:
    """结果分析器：从数值数据中提取结论"""

    @staticmethod
    def check_gray_ratio(xPhys) -> float:
        """计算灰度比例"""
        # xPhys 是物理密度场，0-1之间的值
        # 灰度比例 = 介于0.1-0.9之间的单元比例
        if xPhys is None:
            return 1.0
        gray = ((xPhys > 0.1) & (xPhys < 0.9)).sum()
        return gray / xPhys.size

    @staticmethod
    def check_connectivity(xPhys, threshold=0.5) -> int:
        """检查连通分量数"""
        # 实际实现中调用连通分量分析
        # 返回连通分量数
        return 1  # placeholder

    @staticmethod
    def check_compliance_stability(history: list, window=5) -> dict:
        """
        检查柔度稳定性。
        返回: {oscillation: float, trend: str, unstable: bool}
        """
        if len(history) < window + 1:
            return {"oscillation": 0.0, "trend": "unknown", "unstable": False}

        recent = history[-window:]
        osc = max(recent) - min(recent)
        avg = sum(recent) / len(recent)

        return {
            "oscillation": osc,
            "osc_ratio": osc / avg if avg > 0 else 0,
            "trend": "increasing" if recent[-1] > recent[0] else "decreasing",
            "unstable": (osc / avg) > 0.05 if avg > 0 else False
        }

    @staticmethod
    def check_solver_credibility(residual: float, cg_iterations: int) -> dict:
        """
        检查求解可信度。
        返回: {credible: bool, reason: str}
        """
        if residual > 1e-3:
            return {"credible": False, "reason": f"残差超标: {residual:.2e} > 1e-3"}
        if cg_iterations > 500:
            return {"credible": False, "reason": f"PCG迭代过多: {cg_iterations} > 500"}
        return {"credible": True, "reason": "求解可信"}


class AuditAgent:
    """
    审计Agent负责：
    - 读取数值结果，分析实验指标
    - 判断假设成立等级
    - 诊断失败原因（参照方案 §7.3 诊断规则）
    - 决定下一轮迭代方向
    """

    def __init__(self, model_client=None):
        self.client = model_client
        self.analyzer = ResultAnalyzer()

    def audit_results(self, results: list[ExperimentResult],
                      hypotheses_set) -> list[AuditVerdict]:
        """
        审计一组实验结果，返回每个假设的裁决。
        """
        verdicts = []

        # 按假设ID分组
        grouped = {}
        for r in results:
            grouped.setdefault(r.hypothesis_id, []).append(r)

        for hid, group_results in grouped.items():
            hypothesis = hypotheses_set.get_by_id(hid)
            verdict = self._evaluate_hypothesis(hid, hypothesis, group_results)
            verdicts.append(verdict)

        return verdicts

    def _evaluate_hypothesis(self, hid: str, hypothesis,
                             results: list[ExperimentResult]) -> AuditVerdict:
        """评估单个假设的实验证据"""
        if not results:
            return AuditVerdict(
                hypothesis_id=hid,
                level=VerdictLevel.INSUFFICIENT_EVIDENCE,
                evidence_summary="无可用实验结果",
                next_action="continue"
            )

        # 检查求解器可信度
        all_credible = all(
            self.analyzer.check_solver_credibility(
                r.solver.get("relative_residual", 1.0),
                r.solver.get("cg_iterations", 1000)
            )["credible"]
            for r in results
        )

        if not all_credible:
            return AuditVerdict(
                hypothesis_id=hid,
                level=VerdictLevel.INSUFFICIENT_EVIDENCE,
                evidence_summary="部分实验求解残差超标，物理解不可信",
                diagnostics=["求解器残差未达标，建议检查预条件器"],
                next_action="reiterate"
            )

        # 检查跨网格结论一致性
        mesh_results = {}
        for r in results:
            mesh = r.solver.get("mesh_level", "unknown")
            mesh_results.setdefault(mesh, []).append(r)

        if len(mesh_results) >= 2:
            consistency = self._check_cross_mesh_consistency(mesh_results)
            if not consistency["consistent"]:
                return AuditVerdict(
                    hypothesis_id=hid,
                    level=VerdictLevel.PARTIALLY_SUPPORTED,
                    evidence_summary=consistency["reason"],
                    diagnostics=["结论跨网格不一致"],
                    applicability_boundary=f"仅在{consistency['valid_meshes']}网格上成立",
                    next_action="continue"
                )

        # 检查灰度比例
        gray_ratios = [r.quality.get("gray_ratio", 1.0) for r in results]
        avg_gray = sum(gray_ratios) / len(gray_ratios)

        # 检查连通性
        all_connected = all(
            r.quality.get("connected_components", 0) == 1
            for r in results
        )

        # 综合判定
        if avg_gray < 0.05 and all_connected:
            return AuditVerdict(
                hypothesis_id=hid,
                level=VerdictLevel.SUPPORTED,
                evidence_summary=f"灰度比例{avg_gray:.3f} < 0.05，全部单连通",
                next_action="stop",
                confidence=0.85
            )
        elif avg_gray < 0.10 and all_connected:
            return AuditVerdict(
                hypothesis_id=hid,
                level=VerdictLevel.PARTIALLY_SUPPORTED,
                evidence_summary=f"灰度比例{avg_gray:.3f}在0.05-0.10之间，连通性良好",
                applicability_boundary="灰度控制达标但未达到严格阈值",
                next_action="continue",
                confidence=0.65
            )
        else:
            diagnostics = []
            if avg_gray >= 0.10:
                diagnostics.append(f"灰度比例{avg_gray:.3f}过高")
            if not all_connected:
                diagnostics.append("出现多连通分量")
            return AuditVerdict(
                hypothesis_id=hid,
                level=VerdictLevel.NOT_SUPPORTED,
                evidence_summary="指标未达到成功条件",
                diagnostics=diagnostics,
                next_action="reiterate",
                confidence=0.7
            )

    def _check_cross_mesh_consistency(self, mesh_results: dict) -> dict:
        """检查跨网格结论一致性"""
        metrics_by_mesh = {}
        for mesh, results in mesh_results.items():
            avg_compliance = sum(r.objective.get("compliance", 0) for r in results) / len(results)
            metrics_by_mesh[mesh] = avg_compliance

        # 简单的尺度一致性检查
        meshes = list(metrics_by_mesh.keys())
        if len(meshes) >= 2:
            values = list(metrics_by_mesh.values())
            relative_diff = abs(values[0] - values[1]) / max(abs(values[0]), abs(values[1]))
            if relative_diff > 0.20:
                return {
                    "consistent": False,
                    "reason": f"不同网格柔度差异{relative_diff:.1%} > 20%",
                    "valid_meshes": meshes[0] if values[0] < values[1] else meshes[1]
                }
        return {"consistent": True, "reason": "跨网格结论一致"}

    def diagnose_failure(self, result: ExperimentResult, expected: dict) -> list:
        """
        失败诊断（参照方案 §7.3 诊断规则）。
        返回诊断列表。
        """
        rules = []
        solver = result.solver
        quality = result.quality

        # 规则1: 残差未达标
        if solver.get("relative_residual", 1.0) > 1e-3:
            rules.append("残差未达标 → 物理解不可信，不更新密度")

        # 规则2: 灰度下降但柔度突增
        if (quality.get("gray_ratio", 1.0) < 0.1 and
                expected.get("compliance", 0) < result.objective.get("compliance", 0) * 1.5):
            rules.append("灰度下降但柔度突增 → 投影过快或陷入局部最优")

        # 规则3: 多连通分量
        if quality.get("connected_components", 1) > 1:
            rules.append("出现多个连通分量 → 细连接被滤除")

        # 规则4: GPU/CPU偏差过大
        if (solver.get("backend", "").startswith("cuda") and
                solver.get("cpu_check_deviation", 0) > 0.01):
            rules.append("GPU/CPU偏差过大 → 精度或内核错误")

        return rules