"""FastAPI boundary for explicitly authorized engineering assistance."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import APIRouter, HTTPException

from agent.llm.client import PiAgentClient
from topoptpilot_desktop.assistant.patches import (
    EngineeringChatRequest,
    EngineeringChatResponse,
    EngineeringPatchRequest,
    PatchProposalResponse,
    generate_engineering_chat,
    generate_patch_proposal,
)
from topoptpilot_desktop.conversations import attachment_for_ai
from topoptpilot.api.fastapi_app import service


router = APIRouter(prefix="/api/engineering/assistant", tags=["engineering-assistant"])


def _vision_chat(messages: list[dict[str, Any]], settings: dict[str, Any]) -> dict[str, Any]:
    key = service.agent_api_key()
    if not key:
        return {"success": False, "content": "", "error": "not_configured"}
    multimodal: list[dict[str, Any]] = []
    for message in messages:
        attachment_ids = message.get("attachmentIds") or []
        if message.get("role") == "user" and attachment_ids:
            blocks: list[dict[str, Any]] = [{"type": "text", "text": str(message.get("content", ""))}]
            for attachment_id in attachment_ids:
                attachment = attachment_for_ai(str(attachment_id))
                if attachment["kind"] == "image":
                    blocks.append({"type": "image_url", "image_url": {"url": attachment["content"]}})
                else:
                    blocks.append({
                        "type": "text",
                        "text": "附件 " + attachment["fileName"] + ":\n" + attachment["content"],
                    })
            multimodal.append({"role": "user", "content": blocks})
        else:
            multimodal.append({
                "role": message.get("role", "user"),
                "content": str(message.get("content", "")),
            })
    payload = json.dumps({
        # Attachments use the same model selected in Settings as ordinary chat.
        # Do not silently route multimodal messages to a separate vision model.
        "model": settings["model"],
        "messages": multimodal,
        "temperature": 0.1,
        "max_tokens": 4096,
    }, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(
        settings["base_url"].rstrip("/") + "/chat/completions",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(request, timeout=settings["timeout_seconds"]) as response:
            result = json.loads(response.read().decode("utf-8"))
        content = result["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("vision_not_supported")
        return {"success": True, "content": content.strip(), "error": None}
    except (urlerror.HTTPError, urlerror.URLError, KeyError, ValueError, TypeError) as exc:
        raise RuntimeError("vision_not_supported：当前视觉模型不可用或拒绝了图片请求") from exc


def _model_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = service.get_settings()["agent"]
    if any(message.get("attachmentIds") for message in messages):
        return _vision_chat(messages, settings)
    client = PiAgentClient(
        api_key=service.agent_api_key(),
        base_url=settings["base_url"],
        model=settings["model"],
        timeout=settings["timeout_seconds"],
        max_retries=settings["max_retries"],
    )
    return client.chat(messages, temperature=0.1, max_tokens=4096)


@router.post("/chat", response_model=EngineeringChatResponse)
def engineering_chat(request: EngineeringChatRequest) -> EngineeringChatResponse:
    try:
        configured = service.get_settings().get("api_key_status") not in {
            "not_configured", "environment_missing",
        }
        return generate_engineering_chat(request, _model_chat, configured=bool(configured))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/patch", response_model=PatchProposalResponse)
def engineering_patch(request: EngineeringPatchRequest) -> PatchProposalResponse:
    try:
        return generate_patch_proposal(request, _model_chat)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc