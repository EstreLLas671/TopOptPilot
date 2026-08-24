from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from idesktop_v2.api.app import app
from idesktop_v2.assistant import router as assistant_router

from idesktop_v2.assistant.patches import EngineeringPatchRequest, generate_patch_proposal


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
