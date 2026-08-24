"""Read the Qwen credential from the process environment only.

Secrets never enter AppSettings, SQLite, logs, reports, reproduction bundles,
or operating-system credential stores.
"""
from __future__ import annotations

import os


def get_qwen_api_key() -> str:
    return os.environ.get("DASHSCOPE_API_KEY", "")


def qwen_api_key_source() -> str:
    return "environment" if os.environ.get("DASHSCOPE_API_KEY") else "not_configured"
