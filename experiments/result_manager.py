"""
实验结果管理器

职责：
1. 解析 MATLAB/CUDA MEX 返回的原始结果
2. 标准化为方案 附录B 格式
3. 累积到 results_store 供 AuditAgent 使用
"""

import json
import math
from pathlib import Path
from typing import Optional

from agent.roles.audit_agent import ExperimentResult, AuditVerdict, \
    VerdictLevel, ResultAnalyzer


class ResultManager:
    """实验结果管理器"""

    def __init__(self, storage_dir: str = "experiments/output"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.analyzer = ResultAnalyzer()

    def load_result(self, result_path: str) -> Optional[ExperimentResult]:
        """加载一个结果文件"""
        try:
            with open(result_path) as f:
                raw = json.load(f)
            return ExperimentResult(
                run_id=raw.get("run_id", ""),
                task_id=raw.get("task_id", ""),
                status=raw.get("status", ""),
                objective=raw.get("objective", {}),
                constraints=raw.get("constraints", {}),
                quality=raw.get("quality", {}),
                solver=raw.get("solver", {}),
                artifacts=raw.get("artifacts", {}),
                hypothesis_id=raw.get("hypothesis_id", ""),
                experiment_group=raw.get("experiment_group", "")
            )
        except Exception as e:
            print(f"加载结果失败 {result_path}: {e}")
            return None

    def load_all(self) -> list[ExperimentResult]:
        """加载所有结果文件"""
        results = []
        for fpath in self.storage_dir.glob("*_result.json"):
            r = self.load_result(str(fpath))
            if r:
                results.append(r)
        return results

    def compute_metrics(self, results: list[ExperimentResult]) -> dict:
        """计算聚合指标"""
        if not results:
            return {}

        return {
            "avg_compliance": sum(r.objective.get("compliance", 0)
                                  for r in results) / len(results),
            "avg_gray_ratio": sum(r.quality.get("gray_ratio", 0)
                                  for r in results) / len(results),
            "avg_cg_iterations": sum(r.solver.get("cg_iterations", 0)
                                     for r in results) / len(results),
            "avg_solve_time": sum(r.solver.get("solve_time_seconds", 0)
                                  for r in results) / len(results),
            "converged_rate": sum(1 for r in results
                                  if r.status == "converged") / len(results),
            "credible_rate": sum(1 for r in results
                                 if self.analyzer.check_solver_credibility(
                                     r.solver.get("relative_residual", 1.0),
                                     r.solver.get("cg_iterations", 1000)
                                 )["credible"]) / len(results)
        }


class NaNChecker:
    """NaN/Inf 运行时检测器（Phase 0 新增）"""

    @staticmethod
    def check_value(value, name: str) -> list:
        """检查单个值是否合法"""
        issues = []
        if value is None:
            issues.append(f"{name} 为 None")
        elif isinstance(value, (int, float)):
            if math.isnan(value):
                issues.append(f"{name} 为 NaN")
            elif math.isinf(value):
                issues.append(f"{name} 为 Inf ({value})")
        return issues

    @staticmethod
    def check_result(result_dict: dict) -> list:
        """检查实验结果字典中所有数值字段（跳过 None 值）"""
        issues = []

        # 仅检查存在的字段
        optional_fields = [
            ("compliance", result_dict.get("compliance")),
            ("gray_ratio", result_dict.get("gray_ratio")),
            ("residual", result_dict.get("residual")),
            ("cg_iterations", result_dict.get("cg_iterations")),
        ]

        for name, value in optional_fields:
            if value is not None:
                issues.extend(NaNChecker.check_value(value, name))

        # 检查非预期值
        gray = result_dict.get("gray_ratio")
        if gray is not None and isinstance(gray, (int, float)):
            if gray < 0 or gray > 1:
                issues.append(f"gray_ratio={gray} 超出 [0,1] 范围")

        residual = result_dict.get("residual")
        if residual is not None and isinstance(residual, (int, float)):
            if residual < 0:
                issues.append(f"residual={residual} 为负数")

        return issues

    @staticmethod
    def has_nan(result_dict: dict) -> bool:
        """快速判断是否含 NaN"""
        return len(NaNChecker.check_result(result_dict)) > 0