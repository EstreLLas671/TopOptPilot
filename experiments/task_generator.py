"""
实验任务生成器

接收 ExperimentAgent 的实验矩阵，生成标准 task.json。
参照方案 §3.3 输入任务示例格式。
"""

import json
import time
from pathlib import Path


def generate_task_json(task: "ExperimentTask", output_dir: str = "experiments/output") -> str:
    """生成标准 task.json 文件"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    task_data = {
        "task_id": task.task_id,
        "research_goal": f"实验组 {task.experiment_group} - 假设 {task.hypothesis_id}",
        "geometry": task.work_package.get("geometry", ""),
        "material": task.work_package.get("material", {}),
        "load_cases": [task.load_case],
        "volume_fraction": task.work_package.get("volume_fraction", 0.40),
        "requirements": task.work_package.get("requirements", {}),
        "solve_options": {
            "solver": task.solver,
            "optimizer": task.optimizer,
            "filter": task.filter,
            "projection": task.projection,
            "controller": task.controller,
            "evaluator": task.evaluator,
            "params": task.params
        },
        "compute_budget": {"max_runs": 1},
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_by": "TopOptPilot.ExperimentAgent"
    }

    # 唯一文件名
    filename = f"{task.task_id}_task.json"
    filepath = output_dir / filename
    with open(filepath, 'w') as f:
        json.dump(task_data, f, indent=2, ensure_ascii=False)

    return str(filepath)