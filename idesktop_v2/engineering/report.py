"""Deterministic Markdown reports for engineering run artifacts."""

from __future__ import annotations

from pathlib import Path


def write_report(record) -> Path:
    path = record.run_dir / "report.md"
    metrics = record.metrics
    lines = [
        f"# iDeskTop v2 工程运行报告",
        "",
        f"- Run ID：`{record.run_id}`",
        f"- 求解链路：`{record.lane.value}`",
        f"- 状态：`{record.status.value}`",
        f"- 配置摘要：`{record.config_digest}`",
        f"- 结果来源：`{record.provenance.get('backend', 'unknown')}` / `solver`",
        "",
        "## 指标",
        "",
    ]
    for key, value in sorted(metrics.items()):
        lines.append(f"- {key}: {value}")
    if record.error:
        lines.extend(["", "## 错误", "", f"- `{record.error.code}`：{record.error.message}"])
    lines.extend(["", "## 制品", ""])
    for ref in record.files:
        lines.append(f"- `{ref.relative_path}` ({ref.size_bytes} bytes, SHA-256 `{ref.sha256}`)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
