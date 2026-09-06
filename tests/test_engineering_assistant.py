from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.assistant import router as assistant_router

from topoptpilot_desktop.assistant.patches import (
    EngineeringChatRequest,
    EngineeringPatchRequest,
    generate_engineering_chat,
    generate_patch_proposal,
)


def _request(**overrides):
    content = "function y = twice(x)\n    y = x * 2;\nend\n"
    values = {
        "projectId": "project-1",
        "relativePath": "solver/twice.m",
        "beforeDigest": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
        "instruction": "Add an input validation guard.",
        "allowExternalSource": True,
    }
    values.update(overrides)
    return EngineeringPatchRequest.model_validate(values)


def test_engineering_assistant_requires_explicit_source_consent_before_chat() -> None:
    calls = []

    with pytest.raises(PermissionError, match="explicit consent"):
        generate_patch_proposal(
            _request(allowExternalSource=False),
            lambda _messages: calls.append(True),
        )

    assert calls == []


def test_engineering_assistant_rejects_stale_content_before_chat() -> None:
    calls = []

    with pytest.raises(ValueError, match="digest"):
        generate_patch_proposal(
            _request(beforeDigest="0" * 64),
            lambda _messages: calls.append(True),
        )

    assert calls == []


def test_engineering_assistant_returns_one_reviewable_patch_proposal() -> None:
    response = {
        "success": True,
        "content": """```diff
--- a/solver/twice.m
+++ b/solver/twice.m
@@ -1,3 +1,4 @@
 function y = twice(x)
+    arguments; x (1,1) double; end
     y = x * 2;
 end
```""",
    }

    proposal = generate_patch_proposal(_request(), lambda _messages: response)

    assert proposal.projectId == "project-1"
    assert proposal.baseDigest == proposal.files[0].beforeDigest
    assert proposal.files[0].relativePath == "solver/twice.m"
    assert proposal.files[0].unifiedDiff.startswith("--- a/solver/twice.m")


def test_engineering_assistant_rejects_a_patch_for_another_file() -> None:
    response = {
        "success": True,
        "content": "--- a/other.m\n+++ b/other.m\n@@ -1 +1 @@\n-old\n+new\n",
    }

    with pytest.raises(ValueError, match="selected file"):
        generate_patch_proposal(_request(), lambda _messages: response)


def test_engineering_assistant_endpoint_rejects_missing_consent() -> None:
    response = TestClient(app).post(
        "/api/engineering/assistant/patch",
        json=_request(allowExternalSource=False).model_dump(),
    )

    assert response.status_code == 403


def test_engineering_assistant_endpoint_returns_a_patch_without_write_access(monkeypatch) -> None:
    captured = []

    def fake_chat(messages):
        captured.extend(messages)
        return {
            "success": True,
            "content": "@@ -1,3 +1,3 @@\n function y = twice(x)\n-    y = x * 2;\n+    y = 2 * x;\n end\n",
        }

    monkeypatch.setattr(assistant_router, "_model_chat", fake_chat)
    response = TestClient(app).post("/api/engineering/assistant/patch", json=_request().model_dump())

    assert response.status_code == 200
    assert response.json()["files"][0]["unifiedDiff"].startswith("@@ -1,3")


def test_engineering_chat_returns_not_configured_without_calling_model() -> None:
    calls = []
    response = generate_engineering_chat(
        EngineeringChatRequest(message="解释当前参数", context={"parameters": {"volfrac": 0.4}}),
        lambda messages: calls.append(messages),
        configured=False,
    )
    assert response.source == "not_configured"
    assert response.actions == []
    assert len(response.contextDigest) == 64
    assert calls == []


def test_engineering_chat_never_sends_source_without_explicit_consent() -> None:
    calls = []
    with pytest.raises(PermissionError, match="explicit consent"):
        generate_engineering_chat(
            EngineeringChatRequest(
                message="解释代码",
                relativePath="solver/example.m",
                context={"source": "secret_source", "fileDigest": "0" * 64},
                allowExternalSource=False,
            ),
            lambda messages: calls.append(messages),
            configured=True,
        )
    assert calls == []


def test_engineering_chat_is_read_only_and_returns_no_secret_or_actions() -> None:
    captured = []
    response = generate_engineering_chat(
        EngineeringChatRequest(message="解释当前结果", context={"runId": "eng-1", "parameters": {"penal": 3}}),
        lambda messages: captured.extend(messages) or {"success": True, "content": "结果解释"},
        configured=True,
    )
    assert response.source == "qwen"
    assert response.reply == "结果解释"
    assert response.actions == []
    assert "api_key" not in response.model_dump_json().lower()
    assert all("secret_source" not in str(message) for message in captured)

def test_engineering_parameter_action_is_structured_and_removed_from_reply() -> None:
    config = {
        "dimension": "3d",
        "bcType": "cantilever",
        "accuracy": "standard",
        "nelx": 24,
        "nely": 8,
        "nelz": 6,
        "volfrac": 0.4,
        "penal": 3.0,
        "rmin": 1.5,
        "maxIterations": 60,
        "minIterations": 8,
        "filterStrategy": "fixed",
        "material": {
            "preset": "normalized",
            "name": "归一化参考材料",
            "youngsModulusGPa": 1.0,
            "poissonRatio": 0.3,
            "densityKgM3": 1.0,
            "yieldStrengthMPa": 1.0,
        },
    }
    import json
    content = (
        "建议提高惩罚因子。"
        "<topoptpilot-action>"
        + json.dumps({
            "type": "apply_optimization_config",
            "config": config,
            "changedFields": ["penal"],
            "rationale": "降低中间密度",
        }, ensure_ascii=False)
        + "</topoptpilot-action>"
    )
    response = generate_engineering_chat(
        EngineeringChatRequest(message="帮我调整参数", context={"parameters": {"penal": 2.5}}),
        lambda _messages: {"success": True, "content": content},
        configured=True,
    )
    assert response.reply == "建议提高惩罚因子。"
    assert response.actions[0]["type"] == "apply_optimization_config"
    assert response.actions[0]["config"]["penal"] == 3.0
    assert "topoptpilot-action" not in response.reply


def test_engineering_partial_parameter_action_merges_current_config() -> None:
    config = {
        "dimension": "3d", "bcType": "cantilever", "accuracy": "standard",
        "nelx": 24, "nely": 8, "nelz": 6, "volfrac": 0.4, "penal": 2.5,
        "rmin": 1.5, "maxIterations": 60, "minIterations": 10,
        "filterStrategy": "fixed", "dimensions": [6, 2, 1.5], "unit": "m",
        "cellSizeMeters": 0.25,
        "material": {"preset": "normalized", "name": "参考材料", "youngsModulusGPa": 1.0,
                     "poissonRatio": 0.3, "densityKgM3": 1.0, "yieldStrengthMPa": 1.0},
    }
    content = (
        "建议将惩罚因子提高到 3。<topoptpilot-action>"
        '{"type":"apply_optimization_config","config":{"penal":3},'
        '"changedFields":["penal"]}</topoptpilot-action>'
    )
    response = generate_engineering_chat(
        EngineeringChatRequest(message="调整惩罚因子", context={"parameters": config}),
        lambda _messages: {"success": True, "content": content}, configured=True,
    )
    assert response.actions[0]["config"]["penal"] == 3
    assert response.actions[0]["config"]["volfrac"] == 0.4
    assert response.actions[0]["changedFields"] == ["penal"]
