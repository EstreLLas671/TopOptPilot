"""
延续调度与控制器 — 把实验 Agent 的投影/反馈参数映射为真实的
beta（Heaviside 投影）与 penal（SIMP 惩罚）迭代调度。

控制器类型 ↔ 实验组：
    fixed_controller          无投影基线（B0）：beta 恒 0，纯 SIMP
    periodic_controller       固定周期调度（B1）：beta 按固定步长/间隔递增
    gray_feedback_controller  灰度反馈（A1）：灰度达标后才提升 beta
    joint_feedback_controller 联合反馈（Ours）：灰度+连通性双反馈，步长更温和

所有控制器返回第 iteration 轮应使用的 beta；gamma（连通性健康度）由
引擎实时传入，保证"反馈 → 下一轮调整"是真实物理驱动而非随机。
"""

from __future__ import annotations

from typing import Optional


class BaseController:
    """控制器基类。子类实现 beta(iteration, ctx) 返回本轮 Heaviside 的 beta。"""

    id: str = "base"
    def __init__(self, params: dict):
        self.p = dict(params or {})
        self.beta_max = float(self.p.get("beta_max", 16) or 0)
        self.beta_step = float(self.p.get("beta_step", 2) or 2)
        self.beta_interval = int(self.p.get("beta_interval", 10) or 10)
        self.gray_threshold = float(self.p.get("gray_threshold", 0.20))

    def beta(self, iteration: int, gray_ratio: Optional[float] = None,
             connected: Optional[int] = None) -> float:
        raise NotImplementedError

    def describe(self) -> str:
        return f"{self.id}(beta_max={self.beta_max})"


class FixedController(BaseController):
    """无投影基线：beta 恒 0，纯 SIMP（对应 B0 / projection=none）。"""
    id = "fixed_controller"

    def beta(self, iteration, gray_ratio=None, connected=None) -> float:
        return 0.0


class PeriodicController(BaseController):
    """固定周期调度（对应 B1）：beta = min(beta_max, step·(it//interval + 1))。

    不受灰度/连通性反馈影响，是"固定调度"的对照基线。
    """
    id = "periodic_controller"

    def beta(self, iteration, gray_ratio=None, connected=None) -> float:
        if self.beta_max <= 0:
            return 0.0
        return min(self.beta_max, self.beta_step * (iteration // self.beta_interval + 1))


class GrayFeedbackController(BaseController):
    """灰度反馈（对应 A1）：灰度未达标（gray > threshold）时延迟 beta 提升。

    体现"观察灰度 → 决定是否继续锐化"的闭环。
    """
    id = "gray_feedback_controller"

    def beta(self, iteration, gray_ratio=None, connected=None) -> float:
        if self.beta_max <= 0:
            return 0.0
        scheduled = self.beta_step * (iteration // self.beta_interval + 1)
        if gray_ratio is not None and gray_ratio > self.gray_threshold:
            scheduled = max(0.0, scheduled - self.beta_step)   # 灰度超标 → 延迟一轮
        return min(self.beta_max, scheduled)


class JointFeedbackController(BaseController):
    """联合反馈（对应 Ours）：灰度 + 连通性双反馈，更温和的步长。

    - 灰度未达标 → 延迟提升
    - 出现断连（connected > 1）→ 延迟提升并保持当前 beta
    结果：在保持连通的前提下达到最低灰度（赛题"逐步提升"叙事终点）。
    """
    id = "joint_feedback_controller"

    def __init__(self, params: dict):
        super().__init__(params)
        # 联合反馈使用更细的步长与更小的间隔，降低过早锐化导致的断连
        if "beta_step" not in (params or {}):
            self.beta_step = 1
        if "beta_interval" not in (params or {}):
            self.beta_interval = 5

    def beta(self, iteration, gray_ratio=None, connected=None) -> float:
        if self.beta_max <= 0:
            return 0.0
        scheduled = self.beta_step * (iteration // self.beta_interval + 1)
        if gray_ratio is not None and gray_ratio > self.gray_threshold:
            scheduled = max(0.0, scheduled - self.beta_step)   # 灰度超标 → 延迟
        if connected is not None and connected > 1:
            scheduled = max(0.0, scheduled - self.beta_step)   # 断连 → 延迟
        return min(self.beta_max, scheduled)


def make_controller(controller_id: str, params: dict) -> BaseController:
    """按插件 ID 构建控制器。未知 ID 回退到 fixed（无投影）。"""
    registry = {
        "fixed_controller": FixedController,
        "periodic_controller": PeriodicController,
        "gray_feedback_controller": GrayFeedbackController,
        "joint_feedback_controller": JointFeedbackController,
    }
    cls = registry.get(controller_id, FixedController)
    return cls(params)


def penal_at_iteration(iteration: int, params: dict) -> float:
    """SIMP 惩罚指数随迭代延续：p(it) = p_start + (p_end-p_start)·min(1, it/p_interval)。

    仅当 params 提供 p_end > p_start 时启用延续，否则保持 p_start 恒定
    （默认路径与经典 99-line 完全一致）。
    """
    p_start = float(params.get("p_start", 3.0) or 3.0)
    p_end = float(params.get("p_end", p_start) or p_start)
    if p_end <= p_start:
        return p_start
    p_interval = max(1, int(params.get("p_interval", 40) or 40))
    frac = min(1.0, iteration / p_interval)
    return p_start + (p_end - p_start) * frac
