"""
Response Parser — 将 LLM 回复解析为结构化数据模型

处理：
1. 纯 JSON 回复 → Pydantic/dict 校验
2. 含 markdown code block 的 JSON → 提取后解析
3. 自由文本回复 → 尝试提取关键字段
4. 降级回复 → 返回默认安全值
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger("TopOptPilot.Parser")


class ResponseParser:
    """LLM 回复解析器"""

    @staticmethod
    def parse_json(text: str) -> dict:
        """
        从 LLM 回复中提取并解析 JSON。

        处理以下格式：
        - 纯 JSON: {"key": "value"}
        - Markdown code block: ```json ... ```
        - 含前缀的 JSON: 思考过程 + {"key": "value"}
        """
        if not text:
            return {}

        # 尝试直接解析
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON code block
        json_match = re.search(
            r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text
        )
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { ... } 块
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning(f"无法解析 LLM 回复为 JSON，返回空 dict")
        return {}

    @staticmethod
    def parse_hypotheses(text: str) -> list:
        """解析假设生成结果"""
        data = ResponseParser.parse_json(text)
        return data.get("hypotheses", [])

    @staticmethod
    def parse_reviews(text: str) -> list:
        """解析审稿结果"""
        data = ResponseParser.parse_json(text)
        return data.get("reviews", [])

    @staticmethod
    def parse_verdicts(text: str) -> list:
        """解析审计结果"""
        data = ResponseParser.parse_json(text)
        return data.get("verdicts", [])

    @staticmethod
    def parse_experiment_tasks(text: str) -> list:
        """解析实验任务列表"""
        data = ResponseParser.parse_json(text)
        if "tasks" in data:
            return data["tasks"]
        if "experiment_group" in data and "tasks" not in data:
            # 单个实验组
            return [data]
        return []

    @staticmethod
    def parse_evidence(text: str) -> dict:
        """解析证据检索结果"""
        data = ResponseParser.parse_json(text)
        return {
            "methods": data.get("methods", []),
            "knowledge_gaps": data.get("knowledge_gaps", []),
            "summary": data.get("summary", ""),
        }

    @staticmethod
    def parse_research_decision(text: str) -> dict:
        """解析研究主管决策"""
        data = ResponseParser.parse_json(text)
        return {
            "action": data.get("action", "continue"),
            "target_state": data.get("target_state", ""),
            "reason": data.get("reason", ""),
            "remaining_budget": data.get("remaining_budget", 30),
        }

    @staticmethod
    def extract_confidence(text: str) -> float:
        """从 LLM 回复中提取置信度（0-1）"""
        data = ResponseParser.parse_json(text)
        verdicts = data.get("verdicts", [])
        if verdicts:
            conf = verdicts[0].get("confidence", 0)
            if isinstance(conf, (int, float)):
                return min(max(float(conf), 0.0), 1.0)
        return 0.5

    @staticmethod
    def safe_get(data: dict, path: str, default=None):
        """安全地通过点号路径获取嵌套值"""
        keys = path.split(".")
        current = data
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return default
            if current is None:
                return default
        return current