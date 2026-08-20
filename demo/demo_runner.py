"""
十分钟演示脚本（参照方案 Section 10.2）

demo_runner.py 编排演示流程的9个阶段。

时间线:
  0:00-0:50   问题与差距
  0:50-1:40   系统架构
  1:40-2:40   上传论文与任务
  2:40-3:40   Paper-to-Plugin
  3:40-4:40   候选假设竞争
  4:40-6:10   真实求解
  6:10-7:20   失败与修正
  7:20-8:30   第二轮与对比
  8:30-9:20   独立复核
  9:20-10:00  研究报告
"""

import time


class DemoRunner:
    """现场演示编排器"""

    def __init__(self):
        self.current_step = 0
        self.total_steps = 9
        self.timeline = [
            {"time": "0:00-0:50", "title": "问题与差距",
             "action": "展示传统方法多、选择难、三维试验成本高"},
            {"time": "0:50-1:40", "title": "系统架构",
             "action": "官方Pi/Qwen做科研决策 -> Safety Policy编译意图 -> Python/MATLAB提供物理真值"},
            {"time": "1:40-2:40", "title": "上传论文与任务",
             "action": "展示真实PDF、支架几何、边界条件"},
            {"time": "2:40-3:40", "title": "Paper-to-Plugin",
             "action": "提取公式、页码、适用条件，生成方法卡片"},
            {"time": "3:40-4:40", "title": "候选假设竞争",
             "action": "生成3项候选，审稿Agent指出断连和局部最优风险"},
            {"time": "4:40-6:10", "title": "真实求解",
             "action": "任务JSON -> CUDA MEX求解 -> 残差/迭代曲线实时更新"},
            {"time": "6:10-7:20", "title": "失败与修正",
             "action": "第一轮过早投影导致断连，Agent回滚并调整控制器"},
            {"time": "7:20-8:30", "title": "第二轮与对比",
             "action": "展示结构、灰度、柔度、连通和时间对比表"},
            {"time": "8:30-9:20", "title": "独立复核",
             "action": "重建网格 -> 独立FEM -> 位移/应力云图"},
            {"time": "9:20-10:00", "title": "研究报告",
             "action": "输出假设等级、适用边界、真实引用、复现包"},
        ]

    def status(self) -> str:
        """当前演示状态"""
        return f"Step {self.current_step}/{self.total_steps}: {self.timeline[self.current_step]['title']}"

    def next(self) -> dict:
        """下一步"""
        if self.current_step < self.total_steps - 1:
            self.current_step += 1
        return self.timeline[self.current_step]

    def get_script(self) -> str:
        """输出完整脚本"""
        lines = []
        for step in self.timeline:
            lines.append(f"[{step['time']}] {step['title']}")
            lines.append(f"  -> {step['action']}")
        return "\n".join(lines)
