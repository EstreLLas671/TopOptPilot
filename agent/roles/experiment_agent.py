"""
实验Agent (Experiment Agent)

职责：从可信插件库选择合法组合，生成任务JSON与对照实验矩阵
输入：候选假设（含排序）、可信插件注册表、计算预算
输出：实验任务JSON列表
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import time


@dataclass
class PluginSpec:
    """插件说明"""
    id: str
    name: str
    version: str
    type: str  # solver / filter / projection / optimizer / controller / evaluator
    status: str  # verified / experimental / candidate
    entry: str  # MATLAB入口函数名


@dataclass
class ExperimentTask:
    """单个实验任务（参照方案 §3.3 输入任务示例）"""
    task_id: str
    experiment_group: str  # B0 / B1 / A1 / A2 / Ours / Ablation
    hypothesis_id: str

    # 插件组合
    solver: str = ""
    optimizer: str = ""
    filter: str = ""
    projection: str = ""
    controller: str = ""
    evaluator: str = ""

    # 参数
    params: dict = field(default_factory=dict)
    load_case: str = ""
    mesh_level: str = "medium"  # coarse / medium / fine

    # 任务包
    work_package: dict = field(default_factory=dict)

    # 状态
    status: str = "pending"  # pending / running / completed / failed


@dataclass
class ExperimentMatrix:
    """实验矩阵（参照方案 §9.4）"""
    tasks: list[ExperimentTask] = field(default_factory=list)
    description: str = ""

    def add_task(self, task: ExperimentTask):
        self.tasks.append(task)

    def total_runs(self) -> int:
        return len(self.tasks)

    def to_json(self, path: str):
        """输出为JSON格式"""
        data = {
            "description": self.description,
            "total_runs": self.total_runs(),
            "tasks": [t.__dict__ for t in self.tasks]
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


class ExperimentAgent:
    """
    实验Agent负责：
    - 根据评审排序结果设计实验
    - 验证插件组合合法性
    - 生成可执行的任务JSON
    - 禁止：调用Experimental插件做正式结论
    """

    def __init__(self, model_client=None, plugin_registry=None):
        self.client = model_client
        self.registry = plugin_registry

    def design_experiment_matrix(self, hypotheses_set, review_results: list,
                                 task_package: dict) -> ExperimentMatrix:
        """
        设计完整实验矩阵。
        参照方案 §9.4 核心实验矩阵。
        """
        matrix = ExperimentMatrix()

        # 从任务包获取场景信息
        load_cases = task_package.get("load_cases", ["vertical"])
        mesh_levels = ["coarse", "medium", "fine"]

        task_idx = 0

        # 为每个假设生成实验
        for h in hypotheses_set.hypotheses:
            # 每个实验在多个网格和载荷下重复
            for load in load_cases:
                for mesh in mesh_levels:
                    task_idx += 1
                    task = ExperimentTask(
                        task_id=f"exp_{time.strftime('%m%d')}_{task_idx:03d}",
                        experiment_group=self._map_hypothesis_to_group(h.id),
                        hypothesis_id=h.id,
                        solver="cuda_mex",
                        optimizer="OC",
                        filter="PDE_filter",
                        projection="Heaviside_projection",
                        controller=self._map_hypothesis_to_controller(h.id),
                        evaluator="standard_evaluator",
                        load_case=load,
                        mesh_level=mesh,
                        params=self._get_params_for_hypothesis(h.id, mesh),
                        work_package={
                            "geometry": task_package.get("geometry", ""),
                            "material": task_package.get("material", {}),
                            "volume_fraction": task_package.get("volume_fraction", 0.40),
                            "requirements": task_package.get("requirements", {})
                        },
                        status="pending"
                    )
                    matrix.add_task(task)

        matrix.description = (
            f"{len(hypotheses_set)}个假设 × "
            f"{len(load_cases)}个载荷 × "
            f"{len(mesh_levels)}个网格 = {matrix.total_runs()}组实验"
        )

        return matrix

    def _map_hypothesis_to_group(self, hid: str) -> str:
        """映射假设ID到实验组（参照方案 §9.4）"""
        mapping = {
            "H1": "Ours",
            "H2": "A1",
            "H3": "B1"
        }
        return mapping.get(hid, "Unknown")

    def _map_hypothesis_to_controller(self, hid: str) -> str:
        """映射假设ID到控制器插件"""
        mapping = {
            "H1": "joint_feedback_controller",
            "H2": "gray_feedback_controller",
            "H3": "periodic_controller"
        }
        return mapping.get(hid, "fixed_controller")

    def _get_params_for_hypothesis(self, hid: str, mesh: str) -> dict:
        """根据假设和网格级别生成参数"""
        param_sets = {
            "H1": {"beta_max": 16, "p_start": 3, "feedback_weights": [0.4, 0.3, 0.2, 0.1]},
            "H2": {"beta_max": 16, "p_start": 3, "gray_threshold": 0.05},
            "H3": {"beta_schedule": "linear", "beta_step": 2, "beta_interval": 10}
        }
        base = param_sets.get(hid, {})
        # 网格级别影响网格相关参数
        base["mesh_level"] = mesh
        return base

    def validate_plugin_combination(self, task: ExperimentTask) -> dict:
        """
        验证插件组合合法性。
        参照方案 §5.4 合法组合规则。
        返回: {valid: bool, reason: str}
        """
        checks = []

        # 1) OC + 体积分数 = 允许（单约束基线）
        if task.optimizer == "OC":
            if not task.work_package.get("requirements", {}).get("stress_constraints"):
                checks.append(("OC_volume_only", True, "OC单约束基线合法"))
            else:
                checks.append(("OC_stress", False, "当前OC接口不支持多约束"))

        # 2) Heaviside + 链式导数 = 必须
        if task.projection == "Heaviside_projection":
            checks.append(("Heaviside_chain", True, "Heaviside返回链式导数"))

        # 3) Experimental插件禁止用于正式结论
        if self.registry:
            for plugin_type in ["solver", "optimizer", "filter", "projection", "controller"]:
                pid = getattr(task, plugin_type, "")
                if pid:
                    spec = self.registry.get_plugin(pid)
                    if spec and spec.status == "experimental":
                        checks.append((f"{pid}_status", False,
                                       f"{pid}为Experimental状态，禁止用于正式结论"))

        all_valid = all(c[1] for c in checks)
        reasons = [c[2] for c in checks]

        return {"valid": all_valid, "checks": reasons}

    def create_task_json(self, task: ExperimentTask) -> dict:
        """
        生成标准任务JSON。
        参照方案 §3.3 输入任务示例格式。
        """
        return {
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
            "compute_budget": {"max_runs": 1}
        }