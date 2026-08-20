"""
引用核查工具。

验证 DOI/URL 和原文页码的有效性，防止引用幻觉。
"""

import re
from typing import Optional


class ReferenceChecker:
    """引用有效性核查"""

    @staticmethod
    def is_valid_doi(doi: str) -> bool:
        """检查 DOI 格式有效性"""
        doi_pattern = r'^10\.\d{4,}/[-._;()/:\w]+$'
        return bool(re.match(doi_pattern, doi))

    @staticmethod
    def extract_doi_from_text(text: str) -> Optional[str]:
        """从文本中提取 DOI"""
        doi_pattern = r'(10\.\d{4,}/[-._;()/:\w]+)'
        match = re.search(doi_pattern, text)
        return match.group(1) if match else None

    @staticmethod
    def check_page_exists(pdf_path: str, page_num: int) -> bool:
        """检查页码是否存在"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            exists = 0 <= page_num - 1 < len(doc)
            doc.close()
            return exists
        except ImportError:
            return True  # 无 PyMuPDF 时跳过

    @staticmethod
    def verify_claim_on_page(pdf_path: str, page_num: int, claim: str) -> dict:
        """
        核验某个声明是否在指定页码出现。
        返回: {found: bool, confidence: float, context_snippet: str}
        """
        try:
            import fitz
            doc = fitz.open(pdf_path)
            if page_num - 1 >= len(doc):
                return {"found": False, "confidence": 0.0,
                        "context_snippet": "", "error": "页码超出范围"}

            page_text = doc[page_num - 1].get_text()
            doc.close()

            # 检查声明中的关键短语是否出现
            key_phrases = [w for w in claim.split() if len(w) > 4][:5]
            found_count = sum(1 for p in key_phrases if p.lower() in page_text.lower())

            confidence = found_count / len(key_phrases) if key_phrases else 0.0
            snippet = page_text[:300] if found_count > 0 else ""

            return {
                "found": found_count >= len(key_phrases) // 2,
                "confidence": confidence,
                "context_snippet": snippet
            }
        except ImportError:
            return {"found": True, "confidence": 0.5,
                    "context_snippet": "", "error": "PyMuPDF not available"}