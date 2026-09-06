"""
Message Builder — 将系统提示词 + 上下文组装为 LLM 消息列表

为每个 Agent 角色提供标准化的消息构建方法，
自动注入当前状态、历史数据、输出格式约束。
"""

import json
from typing import Optional

from agent.prompts.system_prompts import (
    RESEARCH_LEAD_PROMPT,
    EVIDENCE_AGENT_PROMPT,
    HYPOTHESIS_AGENT_PROMPT,
    REVIEW_AGENT_PROMPT,
    EXPERIMENT_AGENT_PROMPT,
    AUDIT_AGENT_PROMPT,
)


class MessageBuilder:
    """为每个 Agent 角色构建 messages 列表"""

    # ============ JSON Schema 输出约束 ============

    RESEARCH_LEAD_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "action": "continue|terminate",
  "target_state": "experiment_design|conclusion",
  "reason": "决策理由",
  "remaining_budget": 30
}
"""

    EVIDENCE_AGENT_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "methods": [
    {
      "method_name": "方法名",
      "method_type": "filter|projection|optimizer|controller|solver|evaluator",
      "description": "简述",
      "source_doi": "10.xxxx/...",
      "source_page": 6,
      "status": "candidate|experimental|verified",
      "relevance_score": 0.85
    }
  ],
  "knowledge_gaps": [
    {
      "description": "知识缺口描述",
      "potential_impact": "high|medium|low"
    }
  ],
  "summary": "检索摘要"
}
"""

    HYPOTHESIS_AGENT_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "hypotheses": [
    {
      "id": "H1",
      "title": "假设标题",
      "statement": "完整假设陈述（必须包含可证伪条件）",
      "reasoning_chain": ["推导1", "推导2"],
      "success_conditions": {"condition_name": "value"},
      "failure_conditions": {"condition_name": "value"},
      "baseline": "基线方案描述",
      "metrics": ["gray_ratio", "compliance"],
      "required_plugins": ["OC", "PDE_filter"],
      "compute_budget_estimate": 8
    }
  ]
}
"""

    REVIEW_AGENT_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "reviews": [
    {
      "hypothesis_id": "H1",
      "scores": {
        "novelty": 0.0,
        "physical_consistency": 0.0,
        "falsifiability": 0.0,
        "compute_cost": 0.0
      },
      "counter_examples": [
        {
          "scenario": "可能失败的具体场景",
          "physical_reason": "物理解释",
          "severity": "high|medium|low"
        }
      ],
      "summary": "评审摘要",
      "rank": 1
    }
  ]
}
"""

    EXPERIMENT_AGENT_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "experiment_group": "Ours",
  "description": "实验组描述",
  "tasks": [
    {
      "task_id": "exp_001",
      "hypothesis_id": "H1",
      "solver": "cuda_mex",
      "optimizer": "OC",
      "filter": "PDE_filter",
      "projection": "heaviside_projection",
      "controller": "joint_feedback_controller",
      "evaluator": "standard_evaluator",
      "load_case": "vertical",
      "mesh_level": "medium",
      "params": {"beta_max": 16, "p_start": 3}
    }
  ],
  "total_runs": 6
}
"""

    AUDIT_AGENT_OUTPUT = """
请严格按以下 JSON 格式输出：
{
  "verdicts": [
    {
      "hypothesis_id": "H1",
      "level": "supported|partially_supported|not_supported|insufficient_evidence",
      "confidence": 0.85,
      "evidence_summary": "证据摘要",
      "diagnostics": ["诊断1"],
      "applicability_boundary": "适用边界描述",
      "next_action": "continue|reiterate|stop"
    }
  ]
}
"""

    # 输出格式映射表
    OUTPUT_FORMATS = {
        "research_lead": RESEARCH_LEAD_OUTPUT,
        "evidence": EVIDENCE_AGENT_OUTPUT,
        "hypothesis": HYPOTHESIS_AGENT_OUTPUT,
        "review": REVIEW_AGENT_OUTPUT,
        "experiment": EXPERIMENT_AGENT_OUTPUT,
        "audit": AUDIT_AGENT_OUTPUT,
    }

    # Prompt 模板映射
    PROMPT_TEMPLATES = {
        "research_lead": RESEARCH_LEAD_PROMPT,
        "evidence": EVIDENCE_AGENT_PROMPT,
        "hypothesis": HYPOTHESIS_AGENT_PROMPT,
        "review": REVIEW_AGENT_PROMPT,
        "experiment": EXPERIMENT_AGENT_PROMPT,
        "audit": AUDIT_AGENT_PROMPT,
    }

    def build(self, role: str, context: dict = None,
              history: list = None, include_output_schema: bool = True) -> list:
        """
        为指定角色构建 messages。

        参数:
            role: "research_lead" | "evidence" | "hypothesis" |
                  "review" | "experiment" | "audit"
            context: 注入 prompt 模板的上下文变量 dict
            history: 可选的历史对话记录
            include_output_schema: 是否追加 JSON Schema 输出约束

        返回: messages list
        """
        # 1. 获取提示词模板
        template = self.PROMPT_TEMPLATES.get(role, "")
        output_schema = self.OUTPUT_FORMATS.get(role, "")

        # 2. 格式化系统提示词
        system_content = template
        if context:
            try:
                system_content = template.format(**context)
            except KeyError as e:
                system_content = template

        # 3. 追加输出格式约束
        if include_output_schema and output_schema:
            system_content += f"\n\n## 输出格式约束\n{output_schema}"

        messages = [{"role": "system", "content": system_content}]

        # 4. 追加历史对话（如果有）
        if history:
            messages.extend(history[-10:])  # 最多保留最近 10 轮

        # 5. 追加用户 prompt
        user_msg = self._build_user_prompt(role, context)
        messages.append({"role": "user", "content": user_msg})

        return messages

    def _build_user_prompt(self, role: str, context: dict) -> str:
        """构建用户消息"""
        prompts = {
            "research_lead": "请分析当前科研状态并做出下一步决策。",
            "evidence": "请检索并分析与当前研究目标相关的论文方法。",
            "hypothesis": "请基于知识缺口生成 3-5 个可证伪候选假设。",
            "review": "请从四维角度评审候选假设并生成反例。",
            "experiment": "请设计实验矩阵并生成可执行任务。",
            "audit": "请分析实验结果并给出结论判定与下一步建议。",
        }
        return prompts.get(role, "请执行你的角色职责。")