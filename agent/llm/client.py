"""PiAgent runtime adapter for TopOptPilot.

The public ``chat`` contract remains compatible with the former wrapper so
research roles can migrate without duplicating business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from dotenv import load_dotenv
from pi_agent.agent_core import Agent, AgentState, AssistantMessage, Model, TextContent
from pi_agent.pi_ai import create_agent_stream_fn, create_default_registry

logger = logging.getLogger("TopOptPilot.PiAgent")

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.7-plus"


class PiAgentClient:
    """Synchronous application adapter over PiAgent's async runtime."""

    framework = "pi-agent"

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, max_retries: int = 3,
                 timeout: int = 120, event_callback: Callable[[dict], None] | None = None):
        load_dotenv()
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("QWEN_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.getenv("QWEN_MODEL", DEFAULT_MODEL)
        self.max_retries = max(1, max_retries)
        self.timeout = timeout
        self.event_callback = event_callback

    def chat(self, messages: list[dict[str, Any]], response_format: dict | None = None,
             temperature: float = 0.3, max_tokens: int = 4096) -> dict[str, Any]:
        """Run one PiAgent turn and return the existing structured envelope.

        PiAgent 0.1 controls its provider payload and does not yet expose the
        sampling arguments. They remain accepted for call-site compatibility.
        """
        del temperature, max_tokens
        if not self.api_key:
            return self._degraded(response_format, "DASHSCOPE_API_KEY is not configured")

        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return _run_async(self._chat_async(messages, response_format))
            except Exception as exc:
                last_error = str(exc)
                logger.warning("PiAgent call failed (attempt %s/%s): %s",
                               attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** (attempt - 1), 4))
        return self._degraded(response_format, last_error or "unknown PiAgent error")

    async def _chat_async(self, messages: list[dict[str, Any]],
                          response_format: dict | None) -> dict[str, Any]:
        system_prompt, prompt = _build_prompt(messages, response_format)
        model = Model(id=self.model, provider="dashscope", api="openai-completions",
                      base_url=self.base_url, reasoning=False)
        state = AgentState(system_prompt=system_prompt, model=model, thinking_level="off")
        registry = create_default_registry()
        agent = Agent(
            initial_state=state,
            stream_fn=create_agent_stream_fn(registry),
            get_api_key=lambda _provider: self.api_key,
            max_retry_delay_ms=min(self.timeout * 1000, 120_000),
        )
        if self.event_callback:
            agent.subscribe(self.event_callback)
        await asyncio.wait_for(agent.prompt(prompt), timeout=self.timeout)

        assistant = next(
            (message for message in reversed(agent.state.messages)
             if isinstance(message, AssistantMessage)), None,
        )
        if assistant is None:
            raise RuntimeError(agent.state.error or "PiAgent returned no assistant message")
        if assistant.error_message:
            raise RuntimeError(assistant.error_message)

        # Never expose ThinkingContent in the Workspace.
        content = "\n".join(
            block.text for block in assistant.content if isinstance(block, TextContent)
        ).strip()
        if not content:
            raise RuntimeError("PiAgent returned an empty final response")
        usage = assistant.usage
        return {
            "success": True,
            "content": content,
            "model": assistant.model or self.model,
            "framework": self.framework,
            "usage": {
                "prompt_tokens": usage.input + usage.cache_read,
                "completion_tokens": usage.output,
                "total_tokens": usage.total_tokens,
            },
            "error": None,
        }

    def _degraded(self, response_format: dict | None, error: str) -> dict[str, Any]:
        if response_format and response_format.get("type") == "json_object":
            content = json.dumps({
                "error": "piagent_unavailable",
                "message": "PiAgent / Qwen is temporarily unavailable",
                "fallback": True,
            }, ensure_ascii=False)
        else:
            content = "[系统降级] PiAgent / Qwen 暂时不可用，跳过本轮模型决策"
        return {
            "success": False, "content": content, "model": self.model,
            "framework": self.framework,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "error": error,
        }

    def update_config(self, api_key: str | None = None, base_url: str | None = None,
                      model: str | None = None) -> None:
        if api_key:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url
        if model:
            self.model = model


def _build_prompt(messages: list[dict[str, Any]], response_format: dict | None) -> tuple[str, str]:
    system_parts = [str(item.get("content", "")) for item in messages
                    if item.get("role") in {"system", "developer"}]
    conversation = []
    for item in messages:
        role = item.get("role", "user")
        if role in {"system", "developer"}:
            continue
        conversation.append(f"{str(role).upper()}:\n{item.get('content', '')}")
    if response_format and response_format.get("type") == "json_object":
        system_parts.append(
            "Return exactly one valid JSON object. Do not wrap the JSON in Markdown and do not "
            "include commentary before or after it."
        )
    return "\n\n".join(system_parts), "\n\n".join(conversation) or "Continue."


def _run_async(coro):
    """Run a coroutine from sync Streamlit/FastAPI code, even with an active loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[Any] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=runner, name="topoptpilot-piagent", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


LLMClient = PiAgentClient

__all__ = ["PiAgentClient", "LLMClient", "DEFAULT_BASE_URL", "DEFAULT_MODEL"]
