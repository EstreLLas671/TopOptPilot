"""
论文阅读工具。

从 PDF 论文中提取结构化信息：方法、公式、参数、适用条件和局限。
基于 PyMuPDF + 可插拔多模态模型实现文档理解；文本推理统一经 PiAgent。
"""

import json
from pathlib import Path
from typing import Optional


class PaperReader:
    """论文 PDF → 结构化方法卡片"""

    def __init__(self):
        self._cached_texts = {}

    def extract_text(self, pdf_path: str) -> str:
        """提取 PDF 文本（使用 PyMuPDF）"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            text = ""
            for page in doc:
                text += f"\n--- Page {page.number + 1} ---\n"
                text += page.get_text()
            doc.close()
            self._cached_texts[pdf_path] = text
            return text
        except ImportError:
            return "[PyMuPDF not installed]"
        except Exception as e:
            return f"[Error reading PDF: {e}]"

    def extract_method_section(self, pdf_path: str, keywords: list[str] = None) -> str:
        """提取论文的方法部分"""
        text = self.extract_text(pdf_path)
        if not text or text.startswith("["):
            return text

        keywords = keywords or ["method", "approach", "formulation",
                                 "topology optimization", "algorithm"]
        lines = text.split("\n")
        method_lines = []
        in_method = False

        for i, line in enumerate(lines):
            if any(k.lower() in line.lower() for k in keywords):
                in_method = True
            if in_method:
                method_lines.append(line)
                if len(method_lines) > 200:  # 限制长度
                    break

        return "\n".join(method_lines)

    def extract_references(self, pdf_path: str) -> list[dict]:
        """提取参考文献列表"""
        text = self.extract_text(pdf_path)
        refs = []
        in_refs = False

        for line in text.split("\n"):
            if line.strip().lower().startswith("reference"):
                in_refs = True
                continue
            if in_refs:
                if line.strip() and len(line.strip()) > 20:
                    refs.append({"raw": line.strip()})
                elif not line.strip() and refs:
                    break

        return refs
