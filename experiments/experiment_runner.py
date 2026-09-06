"""
实验执行器 — 接口占位

职责：
1. 读取 task.json
2. 验证插件组合合法性（通过 PluginRegistry）
3. 调用 MATLAB MCP 执行求解
4. 监控求解进度
5. 返回 result.json

参照方案 §8.1 每次实验输出格式。
"""

import json
import time
from pathlib import Path


class ExperimentRunner:
    """实验执行器"""

    def __init__(self, mcp_matlab=None, mcp_solver=None, plugin_registry=None):
        self.mcp_matlab = mcp_matlab
        self.mcp_solver = mcp_solver
        self.registry = plugin_registry
        self.running_tasks = {}

    def submit(self, task_json_path: str) -> str:
        """提交实验任务，返回 run_id"""
        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}_{len(self.running_tasks):03d}"
        self.running_tasks[run_id] = {
            "task_path": task_json_path,
            "status": "pending",
            "start_time": None,
            "end_time": None,
            "result_path": None
        }
        return run_id

    def run_single(self, task_json_path: str, output_dir: str = "experiments/output") -> dict:
        """
        运行单个实验（同步模式）。

        通过 SolverRunner 调用真实拓扑优化引擎（numpy/scipy 或 MATLAB）。

        返回: result dict（ExperimentResult 兼容，含持久化 artifacts）
        """
        from experiments.solver_runner import SolverRunner

        # task_json_path 可能是任务 JSON 文件或已解析的 dict
        task = task_json_path
        if isinstance(task_json_path, (str, Path)) and Path(task_json_path).exists():
            with open(task_json_path, encoding="utf-8") as f:
                task = json.load(f)

        run_id = f"run_{time.strftime('%Y%m%d_%H%M%S')}"
        return SolverRunner(backend=self.mcp_matlab and "matlab" or "python"
                            ).run_sync(task, run_id=run_id, output_dir=output_dir)

    def poll(self, run_id: str) -> dict:
        """查询任务状态"""
        return self.running_tasks.get(run_id, {"status": "unknown"})

    def get_status_summary(self) -> dict:
        """返回所有任务状态摘要"""
        summary = {"total": len(self.running_tasks), "by_status": {}}
        for rid, info in self.running_tasks.items():
            s = info["status"]
            summary["by_status"][s] = summary["by_status"].get(s, 0) + 1
        return summary