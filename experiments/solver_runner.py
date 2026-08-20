"""
实验求解运行器 — 把 ExperimentTask 交给真实拓扑优化引擎执行。

取代 ExperimentQueue._simulate_run 的随机占位结果（缺口 #3）：
    run(task)  ->  ExperimentResult 兼容的 result dict
    run_sync() ->  额外持久化密度/历史/日志到输出目录

求解后端：
    backend="python"   numpy/scipy 移植（默认，无 MATLAB 依赖）
    backend="matlab"   MATLAB Engine 调用原始 .m（需 matlabengine 包）
    backend="simulate" 旧随机模拟（仅演示预计算）
"""

from __future__ import annotations

import json
import time
from pathlib import Path


class SolverRunner:
    """ExperimentTask / 任务 dict → 真实物理求解结果。"""

    def __init__(self, backend: str = "python", output_dir: str = None):
        self.backend = backend
        self.output_dir = Path(output_dir) if output_dir else None
        self._run_count = 0

    def run(self, task) -> dict:
        """运行一次实验，返回 ExperimentResult 兼容的 dict。

        task: agent.roles.experiment_agent.ExperimentTask 或任务 dict。
        """
        if self.backend == "simulate":
            return self._simulate(task)

        from solver.topopt_engine import run_topopt
        result = run_topopt(task, backend=self.backend)
        self._run_count += 1
        return result

    def run_sync(self, task, run_id: str = "", output_dir: str = None) -> dict:
        """运行并持久化 artifacts 到 output_dir（返回 result，artifacts 指向文件）。

        - density  : 最终物理密度 .npy
        - history  : 柔度/灰度/β 历史 .json
        - log      : 运行摘要 .txt
        """
        result = self.run(task)
        result["run_id"] = run_id or result.get("run_id", "")

        out = Path(output_dir) if output_dir else self.output_dir
        if out is None:
            out = Path("experiments/output")
        out.mkdir(parents=True, exist_ok=True)

        name = f"{result['run_id'] or 'run'}_{self._run_count:03d}"
        density_path = out / f"{name}_density.npy"
        history_path = out / f"{name}_history.json"
        log_path = out / f"{name}_log.txt"

        import numpy as np
        np.save(density_path, np.asarray(result["artifacts"]["density"]))
        with open(history_path, "w", encoding="utf-8") as f:
            json.dump(result["artifacts"]["history"], f, ensure_ascii=False, indent=1)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(self._format_log(result))

        result["artifacts"] = {
            "density": str(density_path),
            "history": str(history_path),
            "log": str(log_path),
        }
        result["_result_path"] = str(history_path)
        return result

    # ------------------------------------------------------------------
    def _simulate(self, task):
        """旧随机模拟（backend="simulate" 时保留，仅演示预计算）。"""
        import random
        wp = getattr(task, "work_package", {}) or {}
        return {
            "run_id": "", "task_id": getattr(task, "task_id", ""),
            "hypothesis_id": getattr(task, "hypothesis_id", ""),
            "experiment_group": getattr(task, "experiment_group", ""),
            "status": "converged" if random.random() > 0.2 else "failed",
            "objective": {"compliance": round(random.uniform(100, 200), 1)},
            "constraints": {"volume_fraction": wp.get("volume_fraction", 0.40)},
            "quality": {
                "gray_ratio": round(random.uniform(0.02, 0.15), 3),
                "connected_components": random.choice([1, 1, 1, 2]),
                "max_displacement_mm": round(random.uniform(0.1, 0.5), 2),
            },
            "solver": {
                "backend": "simulate",
                "relative_residual": 1e-6, "cg_iterations": 0,
                "solve_time_seconds": 0.001,
                "mesh_level": getattr(task, "mesh_level", "medium"),
            },
            "artifacts": {},
        }

    @staticmethod
    def _format_log(result: dict) -> str:
        q, s, o = result["quality"], result["solver"], result["objective"]
        lines = [
            f"TopOptPilot run: {result.get('run_id', '')}",
            f"  task_id        : {result.get('task_id', '')}",
            f"  status         : {result['status']}",
            f"  compliance     : {o['compliance']:.4f}",
            f"  volume_fraction: {result['constraints']['volume_fraction']:.4f}",
            f"  gray_ratio     : {q['gray_ratio']}",
            f"  connected      : {q['connected_components']}",
            f"  residual       : {s['relative_residual']:.2e}",
            f"  iterations     : {s['iterations']}",
            f"  solve_time_s   : {s['solve_time_seconds']}",
            f"  backend        : {s['backend']}",
        ]
        return "\n".join(lines)
