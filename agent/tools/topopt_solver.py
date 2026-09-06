"""
拓扑优化求解工具 — Agent 与真实求解引擎之间的适配层。

包装 `solver.topopt_engine.run_topopt`，把任务描述（ExperimentTask / dict /
任务 JSON 文件）转换为求解引擎可执行的 task_spec，并校验、格式化结果，
供实验 Agent 在推理中直接调用。

用法（与 paper_reader.py 相同的普通类 + 方法模式，无注册表）：
    from agent.tools.topopt_solver import TopOptSolver
    solver = TopOptSolver()
    result = solver.run(task_spec)
    print(solver.summarize(result))
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from solver.topopt_engine import run_topopt


class TopOptSolver:
    """拓扑优化求解器工具（面向 Agent）。

    后端 backend 取值：
      - "python"  : numpy/scipy 移植引擎（默认，无 MATLAB 依赖，开箱即用）
      - "matlab"  : MATLAB Engine 调用原始 .m 文件（需 matlabengine 包）
    """

    def __init__(self, backend: str = "python"):
        self.backend = backend

    def run(self, task_spec) -> dict:
        """运行一次拓扑优化并校验结果。

        参数
        ----
        task_spec:
            ExperimentTask 或 dict（含 load_case / mesh_level / params /
            work_package / projection / controller / filter 等字段）。

        返回
        ----
        dict:
            ExperimentResult 兼容的结果 dict（objective/constraints/quality/
            solver/artifacts 等）。

        异常
        ----
        ValueError:
            当求解失败或 objective.compliance 非正有限值时抛出。
        """
        result = run_topopt(task_spec, backend=self.backend)
        compliance = self._compliance(result)
        if not (compliance is not None and compliance > 0
                and math.isfinite(compliance)):
            raise ValueError(
                f"求解结果无效: objective.compliance={compliance!r}, "
                f"status={result.get('status')!r}")
        return result

    def summarize(self, result: dict) -> str:
        """生成一行中文摘要，供 Agent 推理与实验日志使用。

        示例：`实验 B0: compliance=239.9, gray=0.821, connected=4, status=converged`
        """
        group = (result.get("experiment_group")
                 or result.get("task_id") or "experiment")
        compliance = self._compliance(result)
        quality = result.get("quality", {}) or {}
        gray = quality.get("gray_ratio", float("nan"))
        connected = quality.get("connected_components", 0)
        status = result.get("status", "?")
        return (f"实验 {group}: compliance={compliance:.1f}, "
                f"gray={gray:.3f}, connected={connected}, status={status}")

    def run_from_json(self, task_json_path: str) -> dict:
        """从任务 JSON 文件加载并运行拓扑优化。

        字段映射（对照 demo/sample_inputs/bracket_task.json）：
            load_cases[0]     → load_case
            volume_fraction   → work_package.volume_fraction
            material          → work_package.material

        缺失键以默认值兜底：load_cases 缺省 ["vertical"]、
        volume_fraction 缺省 0.40、material 缺省空字典（引擎使用
        E=1.0 / nu=0.3 默认材料）。
        """
        path = Path(task_json_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        load_cases = data.get("load_cases") or ["vertical"]
        task_spec = {
            "task_id": data.get("task_id", ""),
            "load_case": load_cases[0] if load_cases else "vertical",
            "mesh_level": data.get("mesh_level", "medium"),
            "params": data.get("params") or {},
            "work_package": {
                "volume_fraction": data.get("volume_fraction", 0.40),
                "material": data.get("material") or {},
            },
            "projection": data.get("projection", "none"),
            "controller": data.get("controller", ""),
            "filter": data.get("filter", ""),
        }
        return self.run(task_spec)

    @staticmethod
    def _compliance(result: dict):
        """从结果 dict 中安全提取 objective.compliance。"""
        objective = result.get("objective") or {}
        return objective.get("compliance")
