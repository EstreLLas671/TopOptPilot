"""
实验队列 — 异步提交 + 轮询 + 结果收集

Phase 0 新增：
- submit(task) 提交实验，返回 run_id
- poll(batch_id) 查询进度
- on_complete(batch_id, callback) 完成回调
- get_all_results() 获取全部已完成结果
"""

import time
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum

logger = logging.getLogger("TopOptPilot.ExperimentQueue")


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class QueueEntry:
    """队列中的单个实验条目"""
    run_id: str
    task: "ExperimentTask"
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[dict] = None
    error: Optional[str] = None
    submitted_at: float = 0.0
    completed_at: Optional[float] = None


class ExperimentQueue:
    """异步实验队列

    backend: "python"（真实 numpy/scipy 求解，默认）/ "matlab" /
             "simulate"（旧随机占位，仅演示预计算）
    """

    def __init__(self, backend: str = "python"):
        self._entries: dict[str, QueueEntry] = {}
        self._callbacks: dict[str, list[Callable]] = {}
        self.backend = backend

    def submit(self, task: "ExperimentTask") -> str:
        """
        提交一个实验任务并执行（同步执行，状态机随后轮询）。

        后端由 self.backend 决定：
            "python"   真实 numpy/scipy 拓扑优化求解（默认）
            "matlab"   MATLAB Engine 求解（需 matlabengine）
            "simulate" 旧随机占位结果（仅演示预计算）

        返回 run_id。
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        entry = QueueEntry(
            run_id=run_id,
            task=task,
            status=TaskStatus.PENDING,
            submitted_at=time.time()
        )
        self._entries[run_id] = entry

        # 执行（真实求解或占位模拟）
        self._execute(run_id, task)
        return run_id

    def _execute(self, run_id: str, task: "ExperimentTask"):
        """执行一次实验：调用真实求解器，异常时标记失败。"""
        entry = self._entries[run_id]
        entry.status = TaskStatus.RUNNING

        try:
            from experiments.solver_runner import SolverRunner
            result = SolverRunner(backend=self.backend).run(task)
            result["run_id"] = run_id
            # 与 get_all_results() 的字段契约保持一致
            result.setdefault("task_id", getattr(task, "task_id", ""))
            result.setdefault("hypothesis_id", getattr(task, "hypothesis_id", ""))
            result.setdefault("experiment_group", getattr(task, "experiment_group", ""))
            entry.result = result
            entry.status = TaskStatus.COMPLETED
        except Exception as e:
            logger.error(f"实验执行失败 {run_id}: {e}")
            result = {
                "run_id": run_id,
                "task_id": getattr(task, "task_id", ""),
                "hypothesis_id": getattr(task, "hypothesis_id", ""),
                "experiment_group": getattr(task, "experiment_group", ""),
                "status": "failed",
                "objective": {},
                "constraints": {},
                "quality": {},
                "solver": {"backend": self.backend, "error": str(e)},
                "artifacts": {},
            }
            entry.result = result
            entry.status = TaskStatus.FAILED
            entry.error = str(e)
        entry.completed_at = time.time()

        # 触发回调
        if run_id in self._callbacks:
            for cb in self._callbacks[run_id]:
                try:
                    cb(entry.result)
                except Exception as e:
                    logger.error(f"回调执行失败: {e}")

    def submit_batch(self, tasks: list) -> str:
        """批量提交实验，返回 batch_id"""
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        for task in tasks:
            self.submit(task)
        return batch_id

    def poll(self, run_id: str) -> dict:
        """查询单条任务状态"""
        entry = self._entries.get(run_id)
        if not entry:
            return {"status": "unknown", "error": "run_id 不存在"}
        return {
            "run_id": run_id,
            "status": entry.status.value,
            "task_id": entry.task.task_id,
            "completed": entry.status in (TaskStatus.COMPLETED, TaskStatus.FAILED),
        }

    def get_status_summary(self) -> dict:
        """返回所有任务状态摘要"""
        summary = {"total": len(self._entries), "by_status": {}}
        for entry in self._entries.values():
            s = entry.status.value
            summary["by_status"][s] = summary["by_status"].get(s, 0) + 1
        return summary

    def get_all_results(self) -> list:
        """获取全部已完成的结果"""
        from agent.roles.audit_agent import ExperimentResult
        results = []
        for entry in self._entries.values():
            if entry.status == TaskStatus.COMPLETED and entry.result:
                r = entry.result
                results.append(ExperimentResult(
                    run_id=r.get("run_id", ""),
                    task_id=r.get("task_id", ""),
                    status=r.get("status", "completed"),
                    objective=r.get("objective", {}),
                    constraints=r.get("constraints", {}),
                    quality=r.get("quality", {}),
                    solver=r.get("solver", {}),
                    artifacts=r.get("artifacts", {}),
                    hypothesis_id=r.get("hypothesis_id", ""),
                    experiment_group=r.get("experiment_group", ""),
                ))
        return results

    def on_complete(self, run_id: str, callback: Callable):
        """注册完成回调"""
        if run_id not in self._callbacks:
            self._callbacks[run_id] = []
        self._callbacks[run_id].append(callback)

    def clear(self):
        """清空队列"""
        self._entries.clear()
        self._callbacks.clear()