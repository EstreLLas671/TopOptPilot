"""Template-v2.0 Markdown/PDF reports built only from authoritative Research State."""
from __future__ import annotations

import re
import html
import base64
import mimetypes
import hashlib
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FIELD_LABELS = {
    "geometry": "设计域", "material": "材料属性", "loads": "载荷工况",
    "boundary_conditions": "边界条件", "constraints": "工程约束", "budgets": "预算",
    "volume_fraction": "体积分数", "gray_ratio": "灰度率", "connectivity": "连通性",
    "connected": "连通性要求", "gray_max": "灰度率上限", "penal": "惩罚因子",
    "rmin": "滤波半径", "max_iter": "最大迭代次数", "E": "弹性模量",
    "E_MPa": "弹性模量", "nu": "泊松比", "magnitude": "载荷大小",
    "unit": "单位", "dimensions": "几何尺寸", "type": "类型",
    "dimension": "求解维度", "bcType": "边界与载荷工况", "load_case": "载荷工况",
    "accuracy": "求解精度", "nelx": "X 向单元数", "nely": "Y 向单元数",
    "nelz": "Z 向单元数", "volfrac": "体积分数", "maxIterations": "最大迭代次数",
    "minIterations": "最小迭代次数", "min_iter": "最小迭代次数",
    "filterStrategy": "滤波策略", "filter_strategy": "滤波策略", "filter": "滤波方法",
    "beta": "投影参数", "beta_max": "最大投影参数", "projection": "投影方法",
    "controller": "迭代控制器", "preset": "材料预设", "name": "名称",
    "youngsModulusGPa": "杨氏模量（GPa）", "E_GPa": "杨氏模量（GPa）",
    "poissonRatio": "泊松比", "densityKgM3": "材料密度（kg/m³）",
    "density_kg_m3": "材料密度（kg/m³）", "yieldStrengthMPa": "屈服强度（MPa）",
    "yield_strength_MPa": "屈服强度（MPa）", "allowable_stress_mpa": "许用应力（MPa）",
    "stress_limit_mpa": "应力限值（MPa）", "max_stress_mpa": "最大应力限值（MPa）",
    "volume_tolerance": "体积分数容差", "cell_size_mm": "单元尺寸（mm）",
    "length_unit": "长度单位", "force_unit": "载荷单位", "direction": "方向",
    "location": "施加位置", "nel": "单元数", "grid": "网格规模",
}

VALUE_LABELS = {
    "2d": "二维", "3d": "三维", "fixed": "固定", "adaptive": "自适应",
    "standard": "标准", "high": "高精度", "cantilever": "悬臂梁",
    "simply_supported": "简支结构", "vertical": "竖向载荷",
    "structural-steel": "结构钢", "normalized": "归一化参考材料",
    "density_filter": "密度滤波", "sensitivity_filter": "灵敏度滤波",
    "heaviside_projection": "Heaviside 投影", "none": "无",
}


def field_label(value: str) -> str:
    return FIELD_LABELS.get(value, "其他参数")


def shown(value: Any, missing: str) -> str:
    if value is None or value == "": return missing
    if isinstance(value, bool): return "是" if value else "否"
    if isinstance(value, float): return f"{value:.6g}"
    if isinstance(value, dict):
        return "；".join(f"{field_label(str(key))}：{shown(item, missing)}" for key, item in value.items()) or missing
    if isinstance(value, list):
        return "；".join(shown(item, missing) for item in value) or missing
    text = str(value)
    return VALUE_LABELS.get(text, text)


def safe_report_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value.strip()).strip(" .")
    if not cleaned or len(cleaned) > 120:
        raise ValueError("报告名称必须为 1 至 120 个有效字符")
    return cleaned


def _final_f3_experiment(research: dict[str, Any], experiments: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    def fidelity_code(item: dict[str, Any]) -> str:
        parts = str(item.get("fidelity") or "").split()
        return parts[0] if parts else ""

    candidates = [
        item for item in (experiments if experiments is not None else research.get("experiments") or [])
        if fidelity_code(item) == "F3"
        and item.get("status") == "SUCCESS" and item.get("result")
    ]
    if not candidates:
        return None
    best = research.get("best_experiment") or {}
    if any(item.get("id") == best.get("id") for item in candidates):
        return next(item for item in candidates if item.get("id") == best.get("id"))
    return min(candidates, key=lambda item: (item.get("result") or {}).get("objective", {}).get("compliance", float("inf")))


class ResearchReportGenerator:
    def __init__(self, output_dir: str | Path): self.output_dir = Path(output_dir)

    def generate(self, research: dict[str, Any], *, round_number: int | None = None) -> dict[str, Path]:
        directory = self.output_dir / research["id"] / "reports"; directory.mkdir(parents=True, exist_ok=True)
        stem = f"round-{round_number:02d}" if round_number else "report"
        markdown, pdf = directory / f"{stem}.md", directory / f"{stem}.pdf"
        text = self.render_markdown(research, round_number=round_number)
        markdown.write_text(text, encoding="utf-8"); self.render_pdf(text, pdf)
        return {"markdown": markdown, "pdf": pdf}

    def export(self, research: dict[str, Any], *, name: str,
               output_directory: str | Path, formats: list[str] | tuple[str, ...],
               overwrite: bool = False) -> dict[str, Path]:
        stem = safe_report_name(name)
        selected = tuple(dict.fromkeys(str(item).lower() for item in formats))
        if not selected or any(item not in {"markdown", "pdf"} for item in selected):
            raise ValueError("报告格式仅支持 markdown 和 pdf")
        output = Path(output_directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=True)
        markdown_target = output / f"{stem}.md"
        pdf_target = output / f"{stem}.pdf"
        assets_target = output / f"{stem}_assets"
        targets = [assets_target]
        if "markdown" in selected: targets.append(markdown_target)
        if "pdf" in selected: targets.append(pdf_target)
        if not overwrite and any(item.exists() for item in targets):
            raise FileExistsError("同名报告或资源目录已存在")
        temporary = output / f".{stem}.tmp-{uuid.uuid4().hex}"
        backup = output / f".{stem}.backup-{uuid.uuid4().hex}"
        assets = temporary / f"{stem}_assets"
        installed: list[Path] = []
        temporary.mkdir(parents=True); assets.mkdir()
        try:
            figure_paths = self._copy_report_figures(research, assets, stem)
            text = self.render_markdown(research, figure_paths=figure_paths)
            temp_markdown, temp_pdf = temporary / f"{stem}.md", temporary / f"{stem}.pdf"
            temp_markdown.write_text(text, encoding="utf-8")
            if "pdf" in selected:
                self.render_pdf(text, temp_pdf, image_base=temporary)
            if overwrite:
                backup.mkdir()
                for item in targets:
                    if item.exists(): item.replace(backup / item.name)
            if "markdown" in selected:
                temp_markdown.replace(markdown_target); installed.append(markdown_target)
            if "pdf" in selected:
                temp_pdf.replace(pdf_target); installed.append(pdf_target)
            assets.replace(assets_target); installed.append(assets_target)
        except Exception:
            for item in reversed(installed):
                if item.is_dir(): shutil.rmtree(item, ignore_errors=True)
                elif item.exists(): item.unlink()
            if backup.exists():
                for item in list(backup.iterdir()): item.replace(output / item.name)
            shutil.rmtree(temporary, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
            raise
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        result = {"assets": assets_target}
        if "markdown" in selected: result["markdown"] = markdown_target
        if "pdf" in selected: result["pdf"] = pdf_target
        return result

    @staticmethod
    def _copy_report_figures(research: dict[str, Any], assets: Path,
                             stem: str) -> dict[str, str]:
        final_f3 = _final_f3_experiment(research)
        final_f3_id = (final_f3 or {}).get("id")
        names = {"TOPOLOGY_IMAGE": "图1_最终拓扑构型.png",
                 "STRESS_IMAGE": "图2_应力分布.png",
                 "CONVERGENCE_IMAGE": "图3_收敛曲线.png"}
        lineage = [item for item in research.get("artifact_lineage") or []
                   if item.get("artifact_type") in names and item.get("path")
                   and item.get("experiment_id") == final_f3_id
                   and Path(item["path"]).is_file()]
        lineage.sort(key=lambda item: list(names).index(item["artifact_type"]))
        copied, used = {}, set()
        for item in lineage:
            kind = item["artifact_type"]
            if kind in used: continue
            source = Path(item["path"]).resolve()
            target = assets / names[kind]
            shutil.copy2(source, target)
            if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
                raise OSError(f"报告图像复制校验失败：{source.name}")
            copied[str(source)] = f"{stem}_assets/{target.name}"
            used.add(kind)
        return copied

    def render_markdown(self, research: dict[str, Any], *, round_number: int | None = None,
                        figure_paths: dict[str, str] | None = None) -> str:
        figure_paths = figure_paths or {}
        zh = research.get("locale", "zh-CN") == "zh-CN"; missing = "未计算" if zh else "Not calculated"
        contract = research.get("contract") or {}; experiments = list(research.get("experiments") or [])
        if round_number is not None: experiments = [e for e in experiments if int(e.get("round_number", 1)) <= round_number]
        hypotheses, tasks, lineage = research.get("hypotheses") or [], research.get("subagent_tasks") or [], research.get("artifact_lineage") or []
        completed = [e for e in experiments if e.get("result")]; feasible = [e for e in completed if ((e.get("result") or {}).get("evaluation") or {}).get("success")]
        final_f3 = _final_f3_experiment(research, experiments)
        final_f3_id = (final_f3 or {}).get("id")
        failed = [e for e in experiments if e.get("status") == "FAILED"]
        abnormal = bool(failed) and not completed
        current_round = round_number or research.get("current_round", 0)
        generated = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        sources = contract.get("field_sources") or {}; geometry, material = dict(contract.get("geometry") or {}), contract.get("material") or {}
        configured = ((research.get("defaults") or {}).get("optimization_config") or {})
        if configured:
            geometry.update({key: configured[key] for key in (
                "dimension", "dimensions", "unit", "cellSizeMeters", "accuracy", "nelx", "nely", "nelz"
            ) if key in configured})
        loads, boundary, constraints = contract.get("loads") or [], contract.get("boundary_conditions") or {}, contract.get("constraints") or {}
        user_prompt = contract.get("description") or missing
        summary = (("本次迭代异常终止，没有产生有效对比结果。" if zh else "The iteration terminated abnormally without valid comparison results.") if abnormal else
                   (("尚无成功的 F3 最终优化结果，不能用低保真结果替代最终结论。" if zh else "No successful F3 final result is available; lower-fidelity evidence cannot replace the final conclusion.") if not final_f3 else
                   (("Evaluator 已确认 F3 最终结果可行；结论仍限于已记录工况与约束。" if zh else "The evaluator marked the F3 final result feasible; the conclusion remains limited to recorded cases and constraints.") if ((final_f3.get("result") or {}).get("evaluation") or {}).get("success") else
                   ("F3 最终结果尚未被 Evaluator 判定为可行，不能宣称设计成功。" if zh else "The F3 final result is not evaluator-feasible; design success cannot be claimed."))))
        lines = ["# TopOptPilot 智能体分析报告" if zh else "# TopOptPilot Agent Analysis Report", "",
            f"**{'报告编号' if zh else 'Report No.'}**：TOP-{str(generated)[:10].replace('-','')}-{research['id']}",
            f"**{'任务标题' if zh else 'Task title'}**：{research.get('name') or missing}", f"**{'生成时间' if zh else 'Generated'}**：{generated}",
            "**智能体版本**：TopOptPilot 2.0.7", f"**对应任务 ID**：{research['id']}",
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
            "### 2.2 补充明细：设计域与边界条件", "", "| 参数名称 | 设定值/范围 | 说明 |", "| :--- | :--- | :--- |",
            f"| 设计域 | {shown(geometry, missing)} | 真实 Research State 记录 |",
            f"| 边界条件 | {shown(boundary, missing)} | 未记录部分不作推断 |", "",
            "### 2.3 补充明细：材料属性", "", "| 材料属性 | 取值 |", "| :--- | :--- |",
            f"| 材料参数 | {shown(material, missing)} |", "",
            "### 2.4 补充明细：载荷与工况", "", "| 载荷工况 | 设定值 |", "| :--- | :--- |",
            f"| 已记录工况 | {shown(loads, missing)} |", "",
            "### 2.5 工况组合与折减说明（必填）", "", "| 考虑工况 | 未考虑工况 | 原因说明 | 组合/折减系数 |",
            "| :--- | :--- | :--- | :--- |", f"| {shown(loads, missing)} | 未提供 | 仅评估已记录工况 | 未提供 |", "",
            "### 2.6 参数来源清单（必填）", "", "| 参数名称 | 设定值 | 来源/依据 |", "| :--- | :--- | :--- |"]
        for key, value in (("geometry", geometry), ("material", material), ("loads", loads), ("boundary_conditions", boundary), ("constraints", constraints), ("budgets", contract.get("budgets"))):
            lines.append(f"| {field_label(key)} | {shown(value, missing)} | {sources.get(key, 'Research State')} |")
        lines += ["", "## **第三章：算法配置与融合策略（方法透明）**", "",
            "### 3.1 优化问题数学表述", "", "```text",
            "最小化       C(x) = Uᵀ K U                 结构柔度",
            "满足约束     V(x) / V₀ ≤ f                 体积分数约束",
            "             K U = F                       结构平衡方程",
            "             0 < x_min ≤ x_e ≤ 1           单元密度边界", "```", "",
            "### 3.2 符号说明表", "", "| 符号 | 含义 | 单位 |", "| :--- | :--- | :--- |",
            "| x | 单元密度向量 | — |", "| C(x) | 结构柔度 | 由量纲链决定 |",
            "| U | 位移向量 | 由量纲链决定 |", "| K | 整体刚度矩阵 | 由量纲链决定 |",
            "| F | 载荷向量 | 由量纲链决定 |", "| f | 体积分数上限 | — |", "",
            "### 3.3 候选算法与融合逻辑", "", "| 算法/技术 | 作用 | 选用说明 |",
            "| :--- | :--- | :--- |", "| SIMP | 主拓扑优化 | 受控密度法求解 |",
            "| 灵敏度或密度滤波 | 抑制棋盘格与网格依赖 | 取值来自实验参数 |",
            "| OC 更新 | 约束下更新单元密度 | 使用求解器真实迭代 |",
            "| 确定性评估器 | 校验真实结果 | 不使用模型生成指标 |", "",
            "融合逻辑：候选方案经 Policy、安全、预算和审批链后进入真实 FEM 求解；结果由确定性评估器比较，再形成优选与诊断。", "",
            "### 3.4 后处理与可制造化流程（必填）", "", "| 步骤 | 操作 | 说明/参数 |",
            "| :--- | :--- | :--- |", "| 1 | 密度阈值化 | 等值阈值仅用于结果呈现 |",
            "| 2 | 连通性检查 | 基于真实密度场计算连通分量 |",
            "| 3 | 应力后处理 | 单元高斯点 Von Mises 应力 |",
            "| 4 | 三维呈现 | 从 F3 最终密度场提取无单元边线的等值曲面 |",
            "| 5 | 工程复核 | 屈曲、疲劳等未计算项须后续专项校核 |", "",
            "### 3.5 收敛条件与终止准则", "", "```text",
            "柔度变化满足求解器收敛阈值，或达到最大迭代次数；",
            "可行性仅由确定性评估器依据已配置约束判定。", "```", "",
            "### 3.6 运行环境与复现信息", "",
            "| 实验 | 保真度 | 参数摘要 | 求解器变体 | 任务/求解器 SHA-256 |",
            "| :--- | :--- | :--- | :--- | :--- |"]
        for e in experiments:
            solver=(e.get("result") or {}).get("solver") or {}; lines.append(f"| {e['id']} | {e.get('fidelity') or missing} | {shown(e.get('parameters'), missing)} | {e.get('solver_variant') or solver.get('solver_variant') or missing} | {e.get('task_hash') or solver.get('task_sha256') or missing} / {e.get('solver_sha256') or solver.get('solver_entry_sha256') or missing} |")
        lines += ["", "## **第四章：核心优化结果对比**" if zh else "## **Chapter 4: Core result comparison**", ""]
        best=final_f3 or {}; br=best.get("result") or {}; be=br.get("evaluation") or {}
        if abnormal:
            lines += ["### 4.7 异常情况（仅在异常时启用）", "",
                      "> **⚠️ 本次迭代异常终止，无有效对比数据。不得输出成功结论。**", ""]
            lines += [f"- {e['id']}：{e.get('error') or (e.get('result') or {}).get('evaluation',{}).get('failure_type') or '失败原因未提供'}" for e in failed]
            lines.append("")
        else:
            lines += ["### 4.1 方案对比总表", "", "| 方案名称 | 迭代步数 | 最终体积分数 | 最大应力 | 最终柔度 | 灰度率 | 连通分量 | 约束满足 |", "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |"]
            for e in experiments:
                result=e.get("result") or {}; ev=result.get("evaluation") or {}; solver=result.get("solver") or {}; q=result.get("quality") or {}; c=result.get("constraints") or {}; obj=result.get("objective") or {}
                stress = q.get("maximum_von_mises")
                stress_text = (missing if stress is None else
                               f"{shown(stress, missing)} MPa" if q.get("stress_unit_trusted") and q.get("stress_unit") == "MPa"
                               else f"{shown(stress, missing)}（归一化应力）")
                values=[e["id"],shown(solver.get("iterations"),missing),shown(c.get("volume_fraction"),missing),stress_text,shown(obj.get("compliance"),missing),shown(q.get("gray_ratio"),missing),shown(q.get("connected_components"),missing),shown(ev.get("success"),missing)]
                if ev.get("success"): values=[f"**{value}**" for value in values]
                lines.append("| "+" | ".join(values)+" |")
            lines += ["", "### 4.2 关键指标解读", "",
                      "柔度越小表示当前边界与载荷下结构刚度越高；体积分数、灰度率、连通性和最大应力均只解释真实求解器返回值。", "",
                      "### 4.3 需求达成矩阵（必填）", "", "| 需求指标 | 目标值 | 最佳已记录结果 | 是否满足 |", "| :--- | :--- | :--- | :--- |",
                      f"| 体积分数 | {shown(constraints.get('volume_fraction'),missing)} | {shown((br.get('constraints') or {}).get('volume_fraction'),missing)} | {shown((be.get('checks') or {}).get('volume'),missing)} |",
                      f"| 灰度率 | ≤ {shown(constraints.get('gray_max'),missing)} | {shown((br.get('quality') or {}).get('gray_ratio'),missing)} | {shown((be.get('checks') or {}).get('gray'),missing)} |",
                      f"| 连通性 | {shown(constraints.get('connected'),missing)} | {shown((br.get('quality') or {}).get('connected_components'),missing)} | {shown((be.get('checks') or {}).get('connected'),missing)} |", "",
                      "### 4.4 优化结果可视化", ""]
            figure_artifacts=[a for a in lineage if a.get("experiment_id") == final_f3_id and a.get("artifact_type") in {"TOPOLOGY_IMAGE","STRESS_IMAGE","CONVERGENCE_IMAGE"} and a.get("path") and Path(a["path"]).is_file()]
            for artifact in figure_artifacts:
                labels={"TOPOLOGY_IMAGE":"最终拓扑构型","STRESS_IMAGE":"应力分布","CONVERGENCE_IMAGE":"收敛曲线"}
                caption=labels.get(artifact.get("artifact_type"),"真实结果图")
                source=str(Path(artifact["path"]).resolve())
                image_path=figure_paths.get(source, artifact["path"])
                lines += [f"![{caption}]({image_path})", f"*{caption} · SHA-256：{artifact.get('sha256') or missing}*", ""]
            if not figure_artifacts:
                lines += ["> **尚无成功的 F3 最终优化结果；不会使用 F0–F2 图像冒充最终结果。**" if zh else "> **No successful F3 final result is available; F0-F2 figures are not substituted.**", ""]
            best_quality=(br.get("quality") or {})
            stress_limit=next((constraints.get(key) for key in ("allowable_stress_mpa","stress_limit_mpa","max_stress_mpa") if constraints.get(key) is not None),None)
            best_stress=best_quality.get("maximum_von_mises")
            stress_display=(missing if best_stress is None else
                            f"{shown(best_stress,missing)} MPa" if best_quality.get("stress_unit_trusted") and best_quality.get("stress_unit")=="MPa"
                            else f"{shown(best_stress,missing)}（归一化应力）")
            lines += ["### 4.5 敏感性/稳健性说明", "",
                      "本轮未执行受控敏感性分析；不得据此推断网格、载荷或材料扰动下的稳健性。", "",
                      "### 4.6 工程校验表", "", "| 校验项 | 限值/要求 | 计算结果 | 是否满足 |",
                      "| :--- | :--- | :--- | :--- |",
                      f"| 应力校验 | {('≤ '+shown(stress_limit,missing)+' MPa') if stress_limit is not None else '未提供限值'} | {stress_display} | {shown((be.get('checks') or {}).get('stress'),missing) if stress_limit is not None else '未判定'} |",
                      f"| 体积分数校验 | ≤ {shown(constraints.get('volume_fraction'),missing)} | {shown((br.get('constraints') or {}).get('volume_fraction'),missing)} | {shown((be.get('checks') or {}).get('volume'),missing)} |",
                      f"| 连通性检查 | {shown(constraints.get('connected'),missing)} | {shown(best_quality.get('connected_components'),missing)} | {shown((be.get('checks') or {}).get('connected'),missing)} |",
                      "| 可制造性检查 | 未配置完整制造约束 | 未计算 | 未判定 |", ""]
        lines += [
            "## **第五章：可交付文件清单（实物证据）**" if zh else "## **Chapter 5: Deliverables**", ""]
        existing=[a for a in lineage if a.get("path") and Path(a["path"]).exists()]
        artifact_labels={"DENSITY":"密度场数据","STRESS":"应力场数据","HISTORY":"迭代历史","SOLVER_EVIDENCE":"求解器证据","VTK":"三维场数据","TOPOLOGY_IMAGE":"最终拓扑构型图","STRESS_IMAGE":"应力分布图","CONVERGENCE_IMAGE":"收敛曲线图"}
        lines += [f"- `{figure_paths.get(str(Path(a['path']).resolve()),a['path'])}` —— {artifact_labels.get(a.get('artifact_type'), '科研证据制品')}；SHA-256：{a.get('sha256') or missing}" for a in existing] or [f"- {missing}"]
        lines += ["", "## **第六章：结论与审查意见（闭环依据）**", "", "### 6.1 本轮结论摘要", "", summary, "",
                  "### 6.2 需求达成结论", "",
                  ("确定性评估器已判定最终方案满足全部已配置约束。" if be.get("success") is True else "当前证据不足以宣称全部约束满足；未计算或量纲不可信的指标不计为通过。"), "",
                  "### 6.3 迭代历程摘要（必填）", "", "| 轮次 | 实验 | 科学意图 | 结论 |", "| :--- | :--- | :--- | :--- |"]
        for e in experiments: lines.append(f"| {e.get('round_number',1)} | {e['id']} | {e.get('intent') or missing} | {shown(((e.get('result') or {}).get('evaluation') or {}).get('success'),missing)} |")
        lines += ["", "### 6.4 审查决策回显", ""]
        for task in tasks:
            if task.get("role")=="INDEPENDENT_REVIEWER": lines.append(f"- {task['id']} · {task.get('status')} · {shown((task.get('result') or {}).get('text') or task.get('error'),missing)}")
        if not any(t.get("role")=="INDEPENDENT_REVIEWER" for t in tasks): lines.append(f"- {missing}")
        lines += ["", "### 6.5 工程建议与下一步", "",
                  "进入详细设计前，应补充制造约束、网格无关性、屈曲、疲劳和连接节点校核；未计算项不得视为已满足。"]
        knowledge=[]
        for e in experiments:
            for item in e.get("knowledge_ids") or []:
                if item not in knowledge: knowledge.append(item)
        lines += ["", "## **第七章：参考文献与知识来源**" if zh else "## **Chapter 7: References and knowledge sources**", ""]
        lines += [f"- kb:{item}" for item in knowledge] or [f"- {missing}"]
        lines += ["", "*本报告由 TopOptPilot 智能体依据 Research State 与真实求解证据自动生成。*", ""]
        return "\n".join(lines)

    @staticmethod
    def render_pdf(markdown: str, path: Path, *, image_base: Path | None = None) -> None:
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover - compatibility with older bundled runtime
            import fitz
        body = ResearchReportGenerator._markdown_to_html(markdown, image_base or path.parent)
        css = """
        * { box-sizing: border-box; }
        body { font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif; color: #111; font-size: 9.5pt; line-height: 1.55; }
        h1 { color: #000; font-size: 24pt; margin: 18pt 0 16pt; }
        h2 { color: #000; font-size: 15pt; border-bottom: 1.4pt solid #000; padding-bottom: 4pt; margin-top: 18pt; }
        h3 { color: #000; font-size: 11.5pt; margin: 12pt 0 5pt; }
        p { margin: 4pt 0 7pt; } strong { color: #000; }
        blockquote { margin: 5pt 0; padding: 7pt 9pt; background: #fff; border-left: 3pt solid #222; }
        table { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 8.4pt; }
        th { background: #fff; font-weight: bold; } th, td { border: .55pt solid #444; padding: 4pt 5pt; vertical-align: top; }
        pre { background: #fff; border: .5pt solid #777; padding: 7pt; font-size: 7.8pt; white-space: pre-wrap; }
        figure { margin: 10pt 0 8pt; break-inside: avoid; page-break-inside: avoid; }
        figure.figure-page-start { break-before: page; page-break-before: always; }
        figure img { display: block; max-width: 92%; max-height: 275pt; margin: 0 auto 4pt; }
        figcaption { color: #222; font-size: 8pt; font-style: italic; overflow-wrap: anywhere; }
        .rule { border-top: .7pt solid #333; margin: 10pt 0; }
        .footer-note { color: #444; font-size: 8pt; }
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
    def _markdown_to_html(markdown: str, image_base: Path | None = None) -> str:
        """Small deterministic renderer for the report template surface."""
        lines=markdown.splitlines(); output=[]; index=0; in_code=False; code=[]; figure_count=0
        def inline(value: str) -> str:
            escaped=html.escape(value)
            escaped=re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
            escaped=re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", escaped)
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
                if not source.is_absolute():
                    source=((image_base or Path.cwd()) / source).resolve()
                if source.is_file():
                    mime=mimetypes.guess_type(source.name)[0] or "image/png"
                    encoded=base64.b64encode(source.read_bytes()).decode("ascii")
                    caption=""
                    if index+1 < len(lines):
                        caption_match=re.fullmatch(r"\*([^*]+)\*", lines[index+1].strip())
                        if caption_match:
                            caption=f"<figcaption>{inline(caption_match.group(1))}</figcaption>"
                            index+=1
                    figure_class=' class="figure-page-start"' if figure_count == 1 else ""
                    output.append(f'<figure{figure_class}><img alt="{html.escape(image_match.group(1))}" src="data:{mime};base64,{encoded}">{caption}</figure>')
                    figure_count+=1
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
