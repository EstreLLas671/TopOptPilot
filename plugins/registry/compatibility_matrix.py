"""
插件兼容性矩阵

管理插件间的依赖、互斥和兼容关系。
参照方案 §5.1 + §5.4。
"""

VALID_COMBINATIONS = {
    "baseline": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["OC"],
        "filter": ["none", "density_filter", "pde_filter"],
        "projection": ["none"],
        "controller": ["fixed_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "单约束最小柔度基线"
    },
    "heaviside_baseline": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["OC"],
        "filter": ["pde_filter"],
        "projection": ["heaviside_projection"],
        "controller": ["periodic_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "固定轮次β延续"
    },
    "gray_feedback": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["OC"],
        "filter": ["pde_filter"],
        "projection": ["heaviside_projection"],
        "controller": ["gray_feedback_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "单一灰度指标反馈"
    },
    "convergence_feedback": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["OC"],
        "filter": ["pde_filter"],
        "projection": ["heaviside_projection"],
        "controller": ["convergence_feedback_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "收敛稳定性反馈"
    },
    "joint_feedback": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["OC"],
        "filter": ["pde_filter"],
        "projection": ["heaviside_projection"],
        "controller": ["joint_feedback_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "联合反馈（灰度+柔度+连通+求解难度）"
    },
    "mma_extension": {
        "solver": ["cpu_top3dxl", "cuda_mex"],
        "optimizer": ["MMA"],
        "filter": ["pde_filter"],
        "projection": ["heaviside_projection"],
        "controller": ["fixed_controller", "joint_feedback_controller"],
        "evaluator": ["standard_evaluator"],
        "note": "MMA多约束（需梯度检查通过）"
    }
}


class CompatibilityMatrix:
    """兼容性矩阵验证器"""

    @staticmethod
    def is_known_combination(combo: dict) -> dict:
        """检查是否为已知合法组合"""
        for name, template in VALID_COMBINATIONS.items():
            match = True
            for key, valid_values in template.items():
                if key == "note":
                    continue
                if key in combo:
                    if combo[key] not in valid_values:
                        match = False
                        break
            if match:
                return {"matched": True, "name": name, "note": template["note"]}
        return {"matched": False, "name": None, "note": "未知组合，需验证"}

    @staticmethod
    def get_valid_controllers_for_objective(objective: str) -> list:
        """根据研究目标推荐合法控制器"""
        mapping = {
            "gray_reduction": ["gray_feedback_controller", "joint_feedback_controller"],
            "compliance_stability": ["convergence_feedback_controller", "joint_feedback_controller"],
            "comprehensive": ["joint_feedback_controller"],
            "fast_baseline": ["fixed_controller", "periodic_controller"],
        }
        return mapping.get(objective, list(VALID_COMBINATIONS.keys()))