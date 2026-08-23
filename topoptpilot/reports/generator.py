"""Template-v2.0 Markdown/PDF reports built only from authoritative Research State."""
from __future__ import annotations

import json
import re
import html
import base64
import mimetypes
from pathlib import Path
from typing import Any


def shown(value: Any, missing: str) -> str:
    if value is None or value == "": return missing
    if isinstance(value, float): return f"{value:.6g}"
    if isinstance(value, (dict, list)): return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


class ResearchReportGenerator:
    def __init__(self, output_dir: str | Path): self.output_dir = Path(output_dir)

    def generate(self, research: dict[str, Any], *, round_number: int | None = None) -> dict[str, Path]:
        directory = self.output_dir / research["id"] / "reports"; directory.mkdir(parents=True, exist_ok=True)
        stem = f"round-{round_number:02d}" if round_number else "report"
        markdown, pdf = directory / f"{stem}.md", directory / f"{stem}.pdf"
        text = self.render_markdown(research, round_number=round_number)
        markdown.write_text(text, encoding="utf-8"); self.render_pdf(text, pdf)
        return {"markdown": markdown, "pdf": pdf}

    def render_markdown(self, research: dict[str, Any], *, round_number: int | None = None) -> str:
        zh = research.get("locale", "zh-CN") == "zh-CN"; missing = "未计算" if zh else "Not calculated"
        contract = research.get("contract") or {}; experiments = list(research.get("experiments") or [])
        if round_number is not None: experiments = [e for e in experiments if int(e.get("round_number", 1)) <= round_number]
        hypotheses, tasks, lineage = research.get("hypotheses") or [], research.get("subagent_tasks") or [], research.get("artifact_lineage") or []
        completed = [e for e in experiments if e.get("result")]; feasible = [e for e in completed if ((e.get("result") or {}).get("evaluation") or {}).get("success")]
        failed = [e for e in experiments if e.get("status") == "FAILED"]
        current_round = round_number or research.get("current_round", 0); generated = contract.get("confirmed_at") or research.get("updated_at") or missing
        sources = contract.get("field_sources") or {}; geometry, material = contract.get("geometry") or {}, contract.get("material") or {}
        loads, boundary, constraints = contract.get("loads") or [], contract.get("boundary_conditions") or {}, contract.get("constraints") or {}
        user_prompt = contract.get("description") or missing
        summary = (("Evaluator 已确认至少一个可行实验；结论仍限于已记录工况与约束。" if zh else "Evaluator confirmed at least one feasible experiment; the conclusion is limited to recorded cases and constraints.") if feasible else
                   ("当前没有实验被 Evaluator 判定为可行，不能宣称设计成功。" if zh else "No experiment is currently marked feasible by Evaluator; design success cannot be claimed."))
        lines = ["# TopOptPilot 智能体分析报告" if zh else "# TopOptPilot Agent Analysis Report", "",
            f"**{'报告编号' if zh else 'Report No.'}**：TOP-{str(generated)[:10].replace('-','')}-{research['id']}",
            f"**{'任务标题' if zh else 'Task title'}**：{research.get('name') or missing}", f"**{'生成时间' if zh else 'Generated'}**：{generated}",
            "**智能体版本**：TopOptPilot V6.0" if zh else "**Agent version**: TopOptPilot V6.0", f"**Task ID**：{research['id']}",
            f"**{'迭代轮次' if zh else 'Rounds'}**：{current_round}", "", "---", "",
            "## **报告摘要**" if zh else "## **Executive summary**", "", summary, "",
            "## **第一章：任务摘要（映射用户需求）**" if zh else "## **Chapter 1: Task summary**", "",
            "### 1.1 用户原始提示词" if zh else "### 1.1 Original user prompt", "", f"> {user_prompt}", "",
            "### 1.2 解析后目标" if zh else "### 1.2 Parsed objective", "",
            "| 目标项 | 解析结果 |" if zh else "| Item | Parsed result |", "| :--- | :--- |",
            f"| {'目标零件' if zh else 'Target part'} | {geometry.get('type') or missing} |", f"| {'优化目标' if zh else 'Objective'} | {research.get('goal') or missing} |",
            f"| {'量化设计指标' if zh else 'Quantitative targets'} | {shown(constraints, missing)} |", "",
            "### 1.3 关键假设与简化声明" if zh else "### 1.3 Assumptions and simplifications", "",
            "| 假设/简化项 | 说明 | 对结果的影响 |" if zh else "| Assumption | Description | Impact |", "| :--- | :--- | :--- |"]
        if hypotheses:
            lines += [f"| {h['id']} | {h.get('statement') or missing} | {'仅在受控实验支持时可形成结论' if zh else 'A conclusion requires controlled experimental support'} |" for h in hypotheses]
        else: lines.append(f"| {missing} | {contract.get('hypothesis') or missing} | {missing} |")
        lines += ["", "### 1.4 设计任务概述" if zh else "### 1.4 Design task overview", "", research.get("goal") or missing, "",
            "## **第二章：关键参数与工程约束（参数回显）**" if zh else "## **Chapter 2: Parameters and engineering constraints**", "",
            "### 2.1 参数回显总表" if zh else "### 2.1 Parameter echo", "", "| 参数类别 | 参数名称 | 设定值/范围 |" if zh else "| Category | Parameter | Value/range |", "| :--- | :--- | :--- |",
            f"| {'设计域' if zh else 'Domain'} | {'几何/尺寸' if zh else 'Geometry/dimensions'} | {shown(geometry, missing)} |", f"| {'材料' if zh else 'Material'} | E / ν | {shown(material, missing)} |",
            f"| {'载荷' if zh else 'Loads'} | {'载荷工况' if zh else 'Load cases'} | {shown(loads, missing)} |", f"| {'边界' if zh else 'Boundary'} | {'约束类型' if zh else 'Constraint type'} | {shown(boundary, missing)} |",
            f"| {'优化' if zh else 'Optimization'} | {'约束' if zh else 'Constraints'} | {shown(constraints, missing)} |", "",
            "### 2.2 参数来源清单" if zh else "### 2.2 Parameter provenance", "", "| 参数名称 | 设定值 | 来源/依据 |" if zh else "| Parameter | Value | Source |", "| :--- | :--- | :--- |"]
        for key, value in (("geometry", geometry), ("material", material), ("loads", loads), ("boundary_conditions", boundary), ("constraints", constraints), ("budgets", contract.get("budgets"))):
            lines.append(f"| {key} | {shown(value, missing)} | {sources.get(key, missing)} |")
        lines += ["", "### 2.3 任务参数快照" if zh else "### 2.3 Contract snapshot", "", "```json", json.dumps(contract or {"status": missing}, ensure_ascii=False, indent=2, default=str), "```", "",
            "## **第三章：算法配置与融合策略（方法透明）**" if zh else "## **Chapter 3: Algorithm configuration and method transparency**", "",
            "### 3.1 优化问题数学表述" if zh else "### 3.1 Mathematical formulation", "", "```text", "minimize      C(x) = Uᵀ K U", "subject to    V(x) / V₀ ≤ f", "              K U = F", "              0 < x_min ≤ x_e ≤ 1", "```", "",
            "### 3.2 算法、融合逻辑与安全链" if zh else "### 3.2 Algorithm, workflow and safety chain", "", "SIMP → sensitivity filter → OC → MATLAB MCP → deterministic Evaluator", "", "Pi Lead → Subagent review → Policy → Safety/Budget/Human Gate → Executor", "",
            "### 3.3 收敛与复现信息" if zh else "### 3.3 Convergence and reproducibility", "", "```text", "stop = solver convergence criterion OR max_iter; feasibility = Evaluator verdict only", "```", "",
            "| Experiment | Fidelity | Parameters | Solver variant | Task/Solver SHA256 |", "| :--- | :--- | :--- | :--- | :--- |"]
        for e in experiments:
            solver=(e.get("result") or {}).get("solver") or {}; lines.append(f"| {e['id']} | {e.get('fidelity') or missing} | {shown(e.get('parameters'), missing)} | {e.get('solver_variant') or solver.get('solver_variant') or missing} | {e.get('task_hash') or solver.get('task_sha256') or missing} / {e.get('solver_sha256') or solver.get('solver_entry_sha256') or missing} |")
        lines += ["", "## **第四章：核心优化结果对比**" if zh else "## **Chapter 4: Core result comparison**", ""]
        if failed and not feasible:
            lines += ["> **⚠️ 本次研究存在失败实验，且无实验被 Evaluator 判定为可行。不得输出成功结论。**" if zh else "> **⚠️ Failed experiments exist and none is marked feasible. A success conclusion is forbidden.**", ""]
            lines += [f"- {e['id']} · {(e.get('result') or {}).get('evaluation',{}).get('failure_type') or missing}: {e.get('error') or missing}" for e in failed]
        lines += ["", "### 4.1 方案对比总表" if zh else "### 4.1 Experiment comparison", "", "| 方案名称 | 迭代步数 | 最终体积分数 | 最大应力 | 最终柔度 | 灰度率 | 连通分量 | 约束满足 |" if zh else "| Experiment | Iterations | Volume | Max stress | Compliance | Gray ratio | Components | Feasible |", "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
        for e in experiments:
            result=e.get("result") or {}; ev=result.get("evaluation") or {}; solver=result.get("solver") or {}; q=result.get("quality") or {}; c=result.get("constraints") or {}; obj=result.get("objective") or {}
            values=[e["id"],shown(solver.get("iterations"),missing),shown(c.get("volume_fraction"),missing),shown(q.get("max_stress"),missing),shown(obj.get("compliance"),missing),shown(q.get("gray_ratio"),missing),shown(q.get("connected_components"),missing),shown(ev.get("success"),missing)]
            if ev.get("success"): values=[f"**{value}**" for value in values]
            lines.append("| "+" | ".join(values)+" |")
        lines += ["", "### 4.2 需求达成矩阵" if zh else "### 4.2 Requirement matrix", "", "| 需求指标 | 目标值 | 最佳已记录结果 | 是否满足 |" if zh else "| Requirement | Target | Best recorded result | Satisfied |", "| :--- | :--- | :--- | :--- |"]
        best=feasible[0] if feasible else (completed[-1] if completed else {}); br=best.get("result") or {}; be=br.get("evaluation") or {}
        lines += [f"| volume_fraction | {shown(constraints.get('volume_fraction'),missing)} | {shown((br.get('constraints') or {}).get('volume_fraction'),missing)} | {shown(be.get('volume_ok'),missing)} |", f"| gray_ratio | ≤ {shown(constraints.get('gray_max'),missing)} | {shown((br.get('quality') or {}).get('gray_ratio'),missing)} | {shown(be.get('gray_ok'),missing)} |", f"| connectivity | {shown(constraints.get('connected'),missing)} | {shown((br.get('quality') or {}).get('connected_components'),missing)} | {shown(be.get('connectivity_ok'),missing)} |", "",
            "### 4.3 真实拓扑与收敛图" if zh else "### 4.3 Real topology and convergence figures", ""]
        figure_artifacts=[a for a in lineage if a.get("artifact_type") in {"TOPOLOGY_IMAGE","CONVERGENCE_IMAGE"} and a.get("path") and Path(a["path"]).is_file()]
        for artifact in figure_artifacts:
            caption=f"{artifact.get('experiment_id') or ''} · {artifact.get('artifact_type')}"
            lines += [f"![{caption}]({artifact['path']})", f"*{caption} · SHA256={artifact.get('sha256') or missing}*", ""]
        if not figure_artifacts: lines += [missing, ""]
        lines += [
            "## **第五章：可交付文件清单（实物证据）**" if zh else "## **Chapter 5: Deliverables**", ""]
        existing=[a for a in lineage if a.get("path") and Path(a["path"]).exists()]
        lines += [f"- `{a['path']}` —— {a.get('artifact_type') or missing}; SHA256={a.get('sha256') or missing}" for a in existing] or [f"- {missing}"]
        lines += ["", "## **第六章：结论与审查意见（闭环依据）**" if zh else "## **Chapter 6: Conclusion and review**", "", "### 6.1 本轮结论摘要" if zh else "### 6.1 Conclusion", "", summary, "", "### 6.2 迭代历程摘要" if zh else "### 6.2 Iteration history", "", "| 轮次 | 实验 | 科学意图 | 结论 |" if zh else "| Round | Experiment | Intent | Verdict |", "| :--- | :--- | :--- | :--- |"]
        for e in experiments: lines.append(f"| {e.get('round_number',1)} | {e['id']} | {e.get('intent') or missing} | {shown(((e.get('result') or {}).get('evaluation') or {}).get('success'),missing)} |")
        lines += ["", "### 6.3 审查决策回显" if zh else "### 6.3 Review decisions", ""]
        for task in tasks:
            if task.get("role")=="INDEPENDENT_REVIEWER": lines.append(f"- {task['id']} · {task.get('status')} · {shown((task.get('result') or {}).get('text') or task.get('error'),missing)}")
        if not any(t.get("role")=="INDEPENDENT_REVIEWER" for t in tasks): lines.append(f"- {missing}")
        knowledge=[]
        for e in experiments:
            for item in e.get("knowledge_ids") or []:
                if item not in knowledge: knowledge.append(item)
        lines += ["", "## **第七章：参考文献与知识来源**" if zh else "## **Chapter 7: References and knowledge sources**", ""]
        lines += [f"- kb:{item}" for item in knowledge] or [f"- {missing}"]
        lines += ["", "*本报告由 TopOptPilot V6.0 依据 Research State 自动生成；未计算字段不作推断。*" if zh else "*Generated by TopOptPilot V6.0 from Research State; unavailable fields are not inferred.*", ""]
        return "\n".join(lines)

    @staticmethod
    def render_pdf(markdown: str, path: Path) -> None:
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover - compatibility with older bundled runtime
            import fitz
        body = ResearchReportGenerator._markdown_to_html(markdown)
        css = """
        * { box-sizing: border-box; }
        body { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif; color: #242a32; font-size: 9.5pt; line-height: 1.55; }
        h1 { color: #173f78; font-size: 24pt; margin: 18pt 0 16pt; }
        h2 { color: #173f78; font-size: 15pt; border-bottom: 1.4pt solid #24599a; padding-bottom: 4pt; margin-top: 18pt; }
        h3 { color: #173f78; font-size: 11.5pt; margin: 12pt 0 5pt; }
        p { margin: 4pt 0 7pt; } strong { color: #173f78; }
        blockquote { margin: 5pt 0; padding: 7pt 9pt; background: #f2f5fa; border-left: 3pt solid #24599a; }
        table { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 8.4pt; }
        th { background: #e9eef6; font-weight: bold; } th, td { border: .45pt solid #7d8794; padding: 4pt 5pt; vertical-align: top; }
        pre { background: #f4f6f8; border: .5pt solid #c7cdd5; padding: 7pt; font-size: 7.8pt; white-space: pre-wrap; }
        img { display: block; max-width: 92%; max-height: 310pt; margin: 10pt auto 4pt; }
        .rule { border-top: .6pt solid #aeb6c1; margin: 10pt 0; }
        .footer-note { color: #626c78; font-size: 8pt; }
        """
        story = fitz.Story(f"<html><body>{body}</body></html>", user_css=css)
        if path.exists(): path.unlink()
        writer = fitz.DocumentWriter(str(path))
        page_rect = fitz.paper_rect("a4")
        content_rect = fitz.Rect(46, 46, page_rect.width - 46, page_rect.height - 45)
        more = True
        while more:
            device = writer.begin_page(page_rect)
            more, _ = story.place(content_rect)
            story.draw(device)
            writer.end_page()
        writer.close()
        del writer, story

    @staticmethod
    def _markdown_to_html(markdown: str) -> str:
        """Small deterministic renderer for the report template surface."""
        lines=markdown.splitlines(); output=[]; index=0; in_code=False; code=[]
        def inline(value: str) -> str:
            escaped=html.escape(value)
            escaped=re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            escaped=re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
            return escaped
        while index < len(lines):
            raw=lines[index]
            if raw.startswith("```"):
                if in_code: output.append("<pre>"+html.escape("\n".join(code))+"</pre>"); code=[]
                in_code=not in_code; index+=1; continue
            if in_code: code.append(raw); index+=1; continue
            image_match=re.fullmatch(r"!\[(.*?)\]\((.+)\)",raw.strip())
            if image_match:
                source=Path(image_match.group(2))
                if source.is_file():
                    mime=mimetypes.guess_type(source.name)[0] or "image/png"
                    encoded=base64.b64encode(source.read_bytes()).decode("ascii")
                    output.append(f'<img alt="{html.escape(image_match.group(1))}" src="data:{mime};base64,{encoded}">')
                index+=1; continue
            if raw.startswith("|") and index+1<len(lines) and re.match(r"^\|[ :\-\|]+\|$",lines[index+1]):
                headers=[cell.strip() for cell in raw.strip("|").split("|")]; index+=2; rows=[]
                while index<len(lines) and lines[index].startswith("|"):
                    rows.append([cell.strip() for cell in lines[index].strip("|").split("|")]); index+=1
                output.append("<table><thead><tr>"+"".join(f"<th>{inline(cell)}</th>" for cell in headers)+"</tr></thead><tbody>"+"".join("<tr>"+"".join(f"<td>{inline(cell)}</td>" for cell in row)+"</tr>" for row in rows)+"</tbody></table>")
                continue
            heading=re.match(r"^(#{1,3})\s+(.*)$",raw)
            if heading:
                level=len(heading.group(1)); output.append(f"<h{level}>{inline(heading.group(2).replace('**',''))}</h{level}>")
            elif raw.startswith("> "): output.append(f"<blockquote>{inline(raw[2:])}</blockquote>")
            elif raw.startswith("- "): output.append(f"<p>• {inline(raw[2:])}</p>")
            elif raw.strip()=="---": output.append('<div class="rule"></div>')
            elif raw.strip(): output.append(f"<p>{inline(raw)}</p>")
            index+=1
        return "\n".join(output)
