from __future__ import annotations

from fastapi.testclient import TestClient

from topoptpilot.api.fastapi_app import app
from topoptpilot.security import credentials
from topoptpilot.service.research_service import ResearchService


def test_qwen_api_key_uses_only_the_process_environment(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(
        credentials,
        "_read_credential",
        lambda: "credential-manager-secret",
        raising=False,
    )

    assert credentials.get_qwen_api_key() == ""
    assert credentials.qwen_api_key_source() == "not_configured"

    monkeypatch.setenv("DASHSCOPE_API_KEY", "environment-secret")
    assert credentials.get_qwen_api_key() == "environment-secret"
    assert credentials.qwen_api_key_source() == "environment"


def test_agent_key_mutation_routes_are_not_public() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert "/api/settings/agent-key" not in paths


def test_agent_key_mutation_is_not_a_service_capability() -> None:
    assert not hasattr(ResearchService, "set_agent_key")
    assert not hasattr(ResearchService, "delete_agent_key")


def test_security_package_does_not_export_key_mutation() -> None:
    assert not hasattr(credentials, "set_qwen_api_key")
    assert not hasattr(credentials, "delete_qwen_api_key")
