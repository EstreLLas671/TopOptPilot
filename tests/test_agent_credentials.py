from __future__ import annotations

from fastapi.testclient import TestClient

from topoptpilot.api.fastapi_app import app
from topoptpilot.security import credentials
from topoptpilot.service.research_service import ResearchService


def test_qwen_api_key_prefers_environment_then_credential_manager(monkeypatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr(credentials, "_read_credential", lambda: "credential-manager-secret")

    assert credentials.get_qwen_api_key() == "credential-manager-secret"
    assert credentials.qwen_api_key_source() == "credential_manager"

    monkeypatch.setenv("DASHSCOPE_API_KEY", "environment-secret")
    assert credentials.get_qwen_api_key() == "environment-secret"
    assert credentials.qwen_api_key_source() == "environment"


def test_agent_credential_routes_are_public_without_exposing_a_read_route() -> None:
    paths = TestClient(app).get("/openapi.json").json()["paths"]

    assert set(paths["/api/settings/agent-key"]) == {"post", "delete"}
    assert set(paths["/api/settings/agent-credential"]) == {"put", "delete"}
    assert "get" not in paths["/api/settings/agent-key"]
    assert "get" not in paths["/api/settings/agent-credential"]


def test_agent_key_mutation_is_a_dedicated_service_capability() -> None:
    assert hasattr(ResearchService, "set_agent_key")
    assert hasattr(ResearchService, "delete_agent_key")


def test_security_package_exports_credential_manager_mutation() -> None:
    assert hasattr(credentials, "set_qwen_api_key")
    assert hasattr(credentials, "delete_qwen_api_key")


def test_service_agent_key_response_never_contains_the_secret(monkeypatch, tmp_path) -> None:
    stored: dict[str, str] = {}
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setattr("topoptpilot.service.research_service.set_qwen_api_key", lambda value: stored.update(key=value))
    monkeypatch.setattr("topoptpilot.service.research_service.get_qwen_api_key", lambda: stored.get("key", ""))
    monkeypatch.setattr("topoptpilot.service.research_service.qwen_api_key_source", lambda: "credential_manager")
    service = ResearchService(tmp_path, enable_agent_runtime=False)

    response = service.set_agent_key("super-secret")

    assert response == {"configured": True, "source": "credential_manager"}
    assert "super-secret" not in repr(response)
    service.close()
