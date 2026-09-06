"""
插件生命周期管理。

状态转换（参照方案 §4.3）:
  Candidate → Experimental → Verified → Deprecated
                ↑_________________________|
                    重新验证后可恢复
"""

from enum import Enum


class PluginStatus(Enum):
    CANDIDATE = "candidate"        # 仅完成论文提炼，不可正式调用
    EXPERIMENTAL = "experimental"  # 有代码原型，仅运行小规模隔离实验
    VERIFIED = "verified"         # 基准复现与一致性通过，可正式使用
    DEPRECATED = "deprecated"     # 已发现缺陷或被替代


PROMOTION_RULES = {
    PluginStatus.CANDIDATE: {
        "to": PluginStatus.EXPERIMENTAL,
        "requirements": [
            "规格说明完整",
            "接口定义完成",
            "至少一个论文证据支撑"
        ]
    },
    PluginStatus.EXPERIMENTAL: {
        "to": PluginStatus.VERIFIED,
        "requirements": [
            "单元测试通过",
            "有限差分梯度检查通过（误差<1e-4）",
            "在二维MBB或悬臂梁上复现预期现象",
            "在小型三维案例上通过稳定性测试",
            "CPU/GPU一致性检查通过",
            "人工批准（算法负责人或教师签字）"
        ]
    },
    PluginStatus.VERIFIED: {
        "to": PluginStatus.DEPRECATED,
        "requirements": [
            "发现不可修复的缺陷",
            "或被更优方法替代",
            "且已记录替代方案"
        ]
    },
    PluginStatus.DEPRECATED: {
        "to": PluginStatus.VERIFIED,
        "requirements": [
            "缺陷已修复",
            "重新通过Experimental→Verified全部验收",
            "重新获得人工批准"
        ]
    }
}


class PluginLifecycle:
    """插件生命周期管理器"""

    @staticmethod
    def can_promote(current: PluginStatus, target: PluginStatus,
                    checks: dict) -> dict:
        """
        检查是否可以升级/降级。

        参数:
            current: 当前状态
            target:  目标状态
            checks:  检查结果字典，key=requirement描述, value=bool

        返回: {allowed: bool, missing: list, message: str}
        """
        if current == target:
            return {"allowed": True, "missing": [], "message": "状态未变更"}

        # 查找规则
        rule = PROMOTION_RULES.get(current)
        if not rule or rule["to"] != target:
            return {
                "allowed": False,
                "missing": [],
                "message": f"不支持从{current.value}到{target.value}的转换"
            }

        missing = [r for r in rule["requirements"] if not checks.get(r, False)]
        if missing:
            return {
                "allowed": False,
                "missing": missing,
                "message": f"缺少 {len(missing)}/{len(rule['requirements'])} 项要求"
            }

        return {
            "allowed": True,
            "missing": [],
            "message": f"满足全部 {len(rule['requirements'])} 项要求，可升级"
        }

    @staticmethod
    def get_current_phase_description(status: PluginStatus) -> str:
        """获取当前状态描述"""
        descriptions = {
            PluginStatus.CANDIDATE: "论文提炼完成，待开发",
            PluginStatus.EXPERIMENTAL: "代码原型可用，仅隔离实验",
            PluginStatus.VERIFIED: "验证通过，可正式使用",
            PluginStatus.DEPRECATED: "已废弃，禁止用于新结论"
        }
        return descriptions.get(status, "未知状态")

    @staticmethod
    def allowed_operations(status: PluginStatus) -> list:
        """获取允许的操作列表"""
        ops = {
            PluginStatus.CANDIDATE: ["生成开发建议", "生成规格文档"],
            PluginStatus.EXPERIMENTAL: ["运行小规模隔离实验", "梯度检查", "基准复现"],
            PluginStatus.VERIFIED: ["进入正式对照实验", "参与报告结论"],
            PluginStatus.DEPRECATED: ["查看历史记录", "重新验证"],
        }
        return ops.get(status, [])