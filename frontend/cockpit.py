"""
科研驾驶舱 — CLI 版本（参照方案 §10.1）

在终端中显示关键面板的简化版本。
完整 Web UI 待实现（React/Electron）。

面板布局（方案 §10.1）：
┌──────────────────────────────────────────────┐
│ 任务区 | 证据区 | 假设区 | 插件区 | 实验区   │
│ 结果区 | 报告区                              │
└──────────────────────────────────────────────┘

当前实现：CLI 面板切换式查看。
"""

import json
from pathlib import Path


class Cockpit:
    """科研驾驶舱 CLI 版本"""

    def __init__(self):
        self.panels = {
            "task": "科研任务",
            "evidence": "论文证据",
            "hypothesis": "候选假设",
            "plugins": "插件状态",
            "experiment": "实验进度",
            "result": "实验结果",
            "report": "研究报告"
        }

    def show_panel(self, panel_name: str, data: dict = None):
        """显示指定面板"""
        name = self.panels.get(panel_name, panel_name)
        print(f"\n{'='*60}")
        print(f"  [面板] {name}")
        print(f"{'='*60}")
        if data:
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print("  (数据未加载)")

    def show_dashboard(self, state_summary: dict):
        """显示全局仪表盘"""
        print(f"\n{'='*60}")
        print(f"  TopOptPilot 科研驾驶舱")
        print(f"{'='*60}")
        print(f"  状态: {state_summary.get('status', 'unknown')}")
        print(f"  迭代: {state_summary.get('iteration', 0)}")
        print(f"  假设: {state_summary.get('hypotheses_count', 0)} 个")
        print(f"  实验: {state_summary.get('experiments_done', 0)}/{state_summary.get('experiments_total', 0)}")
        print(f"  预算剩余: {state_summary.get('budget_remaining', 0)} 次运行")
        print(f"{'='*60}")

    @staticmethod
    def print_plugin_status(plugins: list):
        """打印插件状态表"""
        header = f"{'ID':<30} {'类型':<12} {'状态':<12} {'版本':<10}"
        print(header)
        print("-" * 64)
        for p in plugins:
            print(f"{p.get('id',''):<30} {p.get('type',''):<12} "
                  f"{p.get('status',''):<12} {p.get('version',''):<10}")

    @staticmethod
    def print_experiment_matrix(tasks: list):
        """打印实验矩阵"""
        header = f"{'Task ID':<20} {'组':<6} {'载荷':<10} {'网格':<8} {'控制器':<20}"
        print(header)
        print("-" * 64)
        for t in tasks:
            print(f"{t.get('task_id',''):<20} {t.get('experiment_group',''):<6} "
                  f"{t.get('load_case',''):<10} {t.get('mesh_level',''):<8} "
                  f"{t.get('controller',''):<20}")