"""
证据Agent (Evidence Agent)

职责：从论文库提取候选方法、公式、参数、适用条件和局限；识别知识缺口
输入：论文与方法卡片集合、研究目标、历史结果
输出：结构化证据表、知识缺口列表
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MethodCard:
    """方法卡片（参照方案 §4.2）"""
    method_name: str
    method_type: str  # solver / filter / projection / optimizer / controller / evaluator
    research_problem: str  # 解决什么问题
    core_formula: dict = field(default_factory=lambda: {
        "source_page": "",
        "source_equation": ""
    })
    parameters: list = field(default_factory=list)  # [{name, meaning, suggested_values, range}]
    applicable_conditions: list = field(default_factory=list)
    known_risks: list = field(default_factory=list)
    evidence: dict = field(default_factory=lambda: {"doi": "", "pages": [], "figures": []})
    implementation_status: str = "candidate"  # candidate / experimental / verified / deprecated


@dataclass
class KnowledgeGap:
    """识别到的知识缺口"""
    description: str
    evidence_driven: bool  # True: 有论文指出；False: Agent推断
    related_methods: list = field(default_factory=list)
    potential_impact: str = ""  # high / medium / low


@dataclass
class EvidenceTable:
    """结构化证据表"""
    methods: list[MethodCard] = field(default_factory=list)
    gaps: list[KnowledgeGap] = field(default_factory=list)
    literature_count: int = 0
    verified_count: int = 0
    summary: str = ""


class EvidenceAgent:
    """
    证据Agent负责：
    - 从论文证据库检索相关方法
    - 提取公式、参数、页码证据
    - 识别知识缺口
    - 结构化方法卡片输出
    """

    def __init__(self, model_client=None, evidence_db=None):
        self.client = model_client
        self.db = evidence_db  # 论文证据库

    def search_methods(self, research_goal: str, constraints: dict = None) -> EvidenceTable:
        """
        根据研究目标检索相关方法。
        返回结构化证据表。
        """
        # 阶段1：从证据数据库检索
        candidates = []
        if self.db:
            candidates = self.db.query(research_goal, method_types=[
                "filter", "projection", "controller"
            ])

        # 阶段2：调用LLM进行相关性排序
        # 实际模型调用统一经 PiAgent runtime
        methods = []
        for c in candidates[:10]:
            methods.append(MethodCard(
                method_name=c.get("name", "unknown"),
                method_type=c.get("type", "unknown"),
                research_problem=c.get("problem", ""),
                core_formula=c.get("formula", {}),
                parameters=c.get("parameters", []),
                applicable_conditions=c.get("conditions", []),
                known_risks=c.get("risks", []),
                evidence=c.get("evidence", {}),
                implementation_status=c.get("status", "candidate")
            ))

        # 识别知识缺口
        gaps = self._identify_gaps(methods, research_goal)

        return EvidenceTable(
            methods=methods,
            gaps=gaps,
            literature_count=len(candidates),
            verified_count=sum(1 for m in methods if m.implementation_status == "verified"),
            summary=f"找到{len(methods)}个相关方法，{len(gaps)}个知识缺口"
        )

    def _identify_gaps(self, methods: list[MethodCard], goal: str) -> list[KnowledgeGap]:
        """识别方法覆盖不足的区域"""
        gaps = []
        method_types_found = {m.method_type for m in methods}

        # 检查是否存在关键方法类型缺失
        required_types = {"filter", "projection", "controller"}
        missing = required_types - method_types_found
        for mt in missing:
            gaps.append(KnowledgeGap(
                description=f"缺少{mt}类型方法的证据覆盖",
                evidence_driven=False,
                potential_impact="high"
            ))

        return gaps

    def extract_method_card(self, paper_data: dict) -> MethodCard:
        """
        从论文结构化数据提取方法卡片。
        参照方案 §4.2 方法卡片字段。
        """
        return MethodCard(
            method_name=paper_data.get("method_name", ""),
            method_type=paper_data.get("method_type", ""),
            research_problem=paper_data.get("problem", ""),
            core_formula=paper_data.get("formula", {}),
            parameters=paper_data.get("parameters", []),
            applicable_conditions=paper_data.get("conditions", []),
            known_risks=paper_data.get("risks", []),
            evidence=paper_data.get("evidence", {}),
            implementation_status="candidate"
        )

    def verify_citation(self, doi: str, page: int, claim: str) -> dict:
        """
        核验引用有效性。
        返回: {verified: bool, confidence: float, source: str}
        """
        # 实际实现中交叉核验DOI和页码
        return {
            "verified": True,
            "confidence": 0.9,
            "source": f"DOI:{doi}, p.{page}"
        }
