"""Deterministic Markdown reports for engineering run artifacts."""

from __future__ import annotations

from pathlib import Path


def write_report(record, name: str = "report") -> Path:
    safe_name = "".join(character for character in name.strip() if character not in '<>:"/\\|?*').strip(" .") or "report"
    path = record.run_dir / f"{safe_name}.md"
    report_relative_path = path.relative_to(record.run_dir).as_posix()
    metrics = record.metrics
    lines = [
        f"# TopOptPilot 工程运行报告",
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
        # Reports are derived views of immutable solver evidence. Including a
        # report's own digest, or another regenerable report, makes hashes
        # recursive or stale on a subsequent write.
        if ref.relative_path == report_relative_path or ref.media_type == "text/markdown":
            continue
        lines.append(f"- `{ref.relative_path}` ({ref.size_bytes} bytes, SHA-256 `{ref.sha256}`)")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
