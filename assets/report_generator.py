"""
研究报告生成器

参照方案 Section 8.2 最终用户输出 + Section 8.3 赛题标准字段映射。
"""

import json
from pathlib import Path


class ReportGenerator:
    """生成《科学假设与研究计划》报告"""

    def __init__(self, output_dir: str = "assets/templates"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self, report_data: dict) -> str:
        """生成完整研究报告，参照 Section 8.3 字段映射"""
        report = {
            "Problem Statement": report_data.get("problem_statement", ""),
            "Rationale": {
                "evidence_driven": report_data.get("evidence_summary", ""),
                "knowledge_gaps": report_data.get("knowledge_gaps", [])
            },
            "Technical Details": {
                "llm_framework": "Official Pi RPC + Qwen 3.7 Plus",
                "fem_solver": "Deterministic Python 2D/3D FEM + optional MATLAB",
                "plugins": report_data.get("plugins_used", [])
            },
            "Datasets": {
                "source": report_data.get("source_experiments", []),
                "target": report_data.get("target_experiments", [])
            },
            "Methods": report_data.get("methods", []),
            "Experiments": {
                "baseline": report_data.get("baseline_experiments", []),
                "ablation": report_data.get("ablation_experiments", []),
                "cross_mesh": report_data.get("cross_mesh_experiments", []),
                "multi_load": report_data.get("multi_load_experiments", [])
            },
            "Results": {
                "numerical": report_data.get("numerical_results", {}),
                "negative_results": report_data.get("negative_results", [])
            },
            "Conclusion": {
                "hypothesis_verdicts": report_data.get("verdicts", []),
                "applicability_boundary": report_data.get("boundary", ""),
                "is_final": report_data.get("is_final", False)
            },
            "References": report_data.get("references", [])
        }

        filepath = self.output_dir / "research_report.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        return str(filepath)

    def generate_hypothesis_plan(self, hypothesis_data: dict) -> str:
        """生成《科学假设与研究计划》（赛题字段）"""
        return self.generate_report(hypothesis_data)
