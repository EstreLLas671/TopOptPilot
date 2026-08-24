"""FastAPI boundary for explicitly authorized engineering patch generation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from agent.llm.client import PiAgentClient
from idesktop_v2.assistant.patches import (
    EngineeringPatchRequest,
    PatchProposalResponse,
    generate_patch_proposal,
)
from topoptpilot.api.fastapi_app import service


router = APIRouter(prefix="/api/engineering/assistant", tags=["engineering-assistant"])


def _model_chat(messages: list[dict[str, Any]]) -> dict[str, Any]:
    settings = service.get_settings()["agent"]
    client = PiAgentClient(
        base_url=settings["base_url"],
        model=settings["model"],
        timeout=settings["timeout_seconds"],
        max_retries=settings["max_retries"],
    )
    return client.chat(messages, temperature=0.1, max_tokens=4096)


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
