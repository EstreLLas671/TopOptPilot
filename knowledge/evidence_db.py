"""
论文证据数据库 (Evidence Database)

存储结构化方法卡片，支持：
- 按研究目标/方法类型/状态检索
- 证据溯源（DOI + 页码 + 附图）
- 方法对比与冲突检测
"""

from dataclasses import dataclass, field
from typing import Optional
import json
from pathlib import Path


@dataclass
class EvidenceEntry:
    """一条结构化论文证据（参照方案 §4.2 方法卡片）"""
    method_name: str
    method_type: str
    doi: str
    pages: list
    figures: list
    formula_page: str = ""
    formula_number: str = ""
    parameters: list = field(default_factory=list)
    applicability: list = field(default_factory=list)
    risks: list = field(default_factory=list)
    implementation_status: str = "candidate"


class EvidenceDB:
    """论文证据数据库 — 本地 JSON 存储"""

    def __init__(self, storage_path: str = "knowledge/storage/method_cards"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, EvidenceEntry] = {}
        self._load_all()

    def _load_all(self):
        """从本地文件加载所有方法卡片"""
        for yaml_file in self.storage_path.glob("*.json"):
            with open(yaml_file) as f:
                data = json.load(f)
                entry = EvidenceEntry(**data)
                self._entries[entry.method_name] = entry

    def query(self, research_goal: str, method_types: list = None,
              status: str = None) -> list[dict]:
        """检索相关方法"""
        results = []
        keywords = research_goal.lower().split()

        for entry in self._entries.values():
            # 类型过滤
            if method_types and entry.method_type not in method_types:
                continue
            # 状态过滤
            if status and entry.implementation_status != status:
                continue
            # 关键词匹配（简单实现，后续可升级为向量检索）
            text = f"{entry.method_name} {entry.applicability}".lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                results.append({
                    "name": entry.method_name,
                    "type": entry.method_type,
                    "doi": entry.doi,
                    "pages": entry.pages,
                    "parameters": entry.parameters,
                    "conditions": entry.applicability,
                    "risks": entry.risks,
                    "status": entry.implementation_status,
                    "relevance_score": score
                })

        results.sort(key=lambda r: r["relevance_score"], reverse=True)
        return results

    def add_entry(self, entry: EvidenceEntry):
        """添加一条证据条目"""
        self._entries[entry.method_name] = entry
        # 持久化
        filepath = self.storage_path / f"{entry.method_name.replace(' ', '_')}.json"
        with open(filepath, 'w') as f:
            json.dump(entry.__dict__, f, indent=2, ensure_ascii=False)

    def get_statistics(self) -> dict:
        """返回统计信息"""
        return {
            "total_entries": len(self._entries),
            "by_type": {},
            "by_status": {}
        }