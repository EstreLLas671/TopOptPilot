"""Versioned, offline topology-optimization knowledge retrieval."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


MANIFEST = {
    "topopt-foundations": ("基础", ["SIMP", "OC", "柔度", "体积分数"]),
    "engineering-templates": ("模板", ["MBB", "悬臂梁", "简支梁", "L型", "桥梁"]),
    "solver-parameters": ("求解器", ["penal", "rmin", "beta", "网格", "MATLAB"]),
    "failure-patterns": ("失败诊断", ["断连", "棋盘格", "灰度", "不收敛", "基础设施"]),
    "controlled-comparisons": ("科研方法", ["假设", "对照实验", "因果", "证据"]),
    "matlab-mcp-safety": ("工具", ["MATLAB MCP", "审批", "安全", "F3"]),
    "reporting-rules": ("报告", ["报告", "复现", "证据", "缺失值"]),
}


class KnowledgeBase:
    def __init__(self, store, root: str | Path | None = None):
        self.store = store
        self.root = Path(root or Path(__file__).with_name("documents"))
        self._initialize()
        self.seed()

    def _initialize(self) -> None:
        with self.store.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_documents (
                    id TEXT NOT NULL, locale TEXT NOT NULL, category TEXT NOT NULL,
                    title TEXT NOT NULL, summary TEXT NOT NULL, tags_json TEXT NOT NULL,
                    content TEXT NOT NULL, version TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(id, locale)
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                    id UNINDEXED, locale UNINDEXED, title, summary, tags, content,
                    tokenize='unicode61'
                );
            """)

    def seed(self) -> None:
        from topoptpilot.memory.research_state import utc_now
        import json
        with self.store.connection() as db:
            for path in sorted(self.root.glob("*.md")):
                match = re.match(r"(.+)\.(zh-CN|en-US)\.md$", path.name)
                if not match:
                    continue
                doc_id, locale = match.groups()
                content = path.read_text(encoding="utf-8").strip()
                title = next((line[2:].strip() for line in content.splitlines()
                              if line.startswith("# ")), doc_id)
                summary = next((line.strip() for line in content.splitlines()
                                if line.strip() and not line.startswith("#")), title)
                category, tags = MANIFEST.get(doc_id, ("通用", []))
                db.execute("""INSERT INTO knowledge_documents
                    (id,locale,category,title,summary,tags_json,content,version,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id,locale) DO UPDATE SET
                    category=excluded.category,title=excluded.title,summary=excluded.summary,
                    tags_json=excluded.tags_json,content=excluded.content,
                    version=excluded.version,updated_at=excluded.updated_at""",
                    (doc_id, locale, category, title, summary, json.dumps(tags, ensure_ascii=False),
                     content, "1.0", utc_now()))
            db.execute("DELETE FROM knowledge_fts")
            db.execute("""INSERT INTO knowledge_fts(id,locale,title,summary,tags,content)
                SELECT id,locale,title,summary,tags_json,content FROM knowledge_documents""")

    def search(self, query: str, locale: str = "zh-CN", category: str | None = None,
               limit: int = 8) -> list[dict[str, Any]]:
        query = str(query or "").strip()[:300]
        limit = max(1, min(int(limit), 20))
        params: list[Any] = [locale]
        clauses = ["locale=?"]
        if category:
            clauses.append("category=?")
            params.append(category)
        terms = [term for term in re.split(r"\s+", query) if term]
        if terms:
            likes = []
            for term in terms[:8]:
                likes.append("(title LIKE ? OR summary LIKE ? OR tags_json LIKE ? OR content LIKE ?)")
                params.extend([f"%{term}%"] * 4)
            clauses.append("(" + " OR ".join(likes) + ")")
        params.append(limit)
        with self.store.connection() as db:
            rows = db.execute(f"""SELECT id,locale,category,title,summary,tags_json,version
                FROM knowledge_documents WHERE {' AND '.join(clauses)}
                ORDER BY CASE WHEN title LIKE ? THEN 0 ELSE 1 END, id LIMIT ?"""
                if terms else f"""SELECT id,locale,category,title,summary,tags_json,version
                FROM knowledge_documents WHERE {' AND '.join(clauses)} ORDER BY id LIMIT ?""",
                (*params[:-1], f"%{query}%", params[-1]) if terms else tuple(params)).fetchall()
        import json
        return [{**dict(row), "tags": json.loads(row["tags_json"]),
                 "citation": f"kb:{row['id']}@{row['version']}"} for row in rows]

    def get(self, document_id: str, locale: str = "zh-CN") -> dict[str, Any]:
        with self.store.connection() as db:
            row = db.execute("""SELECT * FROM knowledge_documents
                WHERE id=? AND locale=?""", (document_id, locale)).fetchone()
            if row is None and locale != "zh-CN":
                row = db.execute("""SELECT * FROM knowledge_documents
                    WHERE id=? AND locale='zh-CN'""", (document_id,)).fetchone()
        if row is None:
            raise KeyError(f"Knowledge document {document_id} does not exist")
        import json
        value = dict(row)
        value["tags"] = json.loads(value.pop("tags_json"))
        value["citation"] = f"kb:{value['id']}@{value['version']}"
        return value

    def categories(self, locale: str = "zh-CN") -> list[dict[str, Any]]:
        with self.store.connection() as db:
            rows = db.execute("""SELECT category,COUNT(*) AS count FROM knowledge_documents
                WHERE locale=? GROUP BY category ORDER BY category""", (locale,)).fetchall()
        return [dict(row) for row in rows]
