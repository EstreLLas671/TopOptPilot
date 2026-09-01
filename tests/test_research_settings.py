from __future__ import annotations

from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop import research_router
from topoptpilot.service import ResearchService


def _research(service: ResearchService, *, dimension: int | str = 3) -> dict:
    created = service.create_research({
        "name": "参数迁移测试",
        "goal": "验证参数配置与审计边界",
        "geometry": {"dimension": dimension},
        "budget_total": 4,
        "mode": "COPILOT",
    })
    # Simulate an older Research that predates versioned optimization_config.
    service.store.update_research_json(created["id"], defaults={"experiment": {}})
    return created


def test_research_optimization_config_get_put_and_dimension_migration(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated, dimension=2)
        client = TestClient(app)
        migrated = client.get(f"/api/researches/{created['id']}/optimization-config")
        assert migrated.status_code == 200
        assert migrated.json()["dimension"] == "2d"

        payload = migrated.json() | {"dimension": "3d", "minIterations": 4, "maxIterations": 12}
        saved = client.put(f"/api/researches/{created['id']}/optimization-config", json=payload)
        assert saved.status_code == 200
        assert saved.json()["dimension"] == "3d"
        assert isolated.get_research(created["id"])["defaults"]["optimization_config"] == saved.json()
        assert any(item["kind"] == "CONFIG_UPDATED" for item in isolated.store.list_events(created["id"]))
    finally:
        isolated.close()


def test_research_optimization_config_rejects_invalid_iteration_range(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated)
        response = TestClient(app).put(
            f"/api/researches/{created['id']}/optimization-config",
            json={"minIterations": 20, "maxIterations": 10},
        )
        assert response.status_code == 422
    finally:
        isolated.close()


def test_research_goal_update_creates_an_audit_event(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated)
        response = TestClient(app).put(
            f"/api/researches/{created['id']}/goal",
            json={"goal": "降低柔顺度，同时约束材料用量"},
        )
        assert response.status_code == 200
        event = isolated.store.list_events(created["id"])[-1]
        assert event["kind"] == "GOAL_UPDATED"
        assert event["payload"]["previous"] == "验证参数配置与审计边界"
        assert event["payload"]["current"] == "降低柔顺度，同时约束材料用量"
    finally:
        isolated.close()

def test_research_chat_does_not_persist_message_bodies_in_sqlite(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    monkeypatch.setattr(
        research_router,
        "_model_chat",
        lambda _messages: {"success": True, "content": "仅返回到本地会话的真实回复"},
    )
    try:
        created = _research(isolated)
        marker = "PRIVATE_CHAT_MARKER_7B3F"
        before = isolated.store.list_events(created["id"])
        response = TestClient(app).post(
            f"/api/research/{created['id']}/chat",
            json={"message": marker},
        )
        assert response.status_code == 200
        assert response.json()["reply"] == "仅返回到本地会话的真实回复"
        after = isolated.store.list_events(created["id"])
        assert after == before
        assert marker not in str(isolated.get_research(created["id"]))
        assert marker not in str(after)
        assert response.json()["contextDigest"]
    finally:
        isolated.close()

def test_research_hypothesis_update_versions_and_audits(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated)
        response = TestClient(app).put(
            f"/api/researches/{created['id']}/hypothesis",
            json={"hypothesis": "增大滤波半径将降低中间密度单元比例"},
        )
        assert response.status_code == 200
        assert response.json()["hypothesis"] == "增大滤波半径将降低中间密度单元比例"
        versions = isolated.store.list_hypotheses(created["id"])
        assert versions[-1]["statement"] == "增大滤波半径将降低中间密度单元比例"
        assert isolated.store.list_events(created["id"])[-1]["kind"] == "HYPOTHESIS_UPDATED"
    finally:
        isolated.close()


def test_research_agent_suggestion_requires_confirmation_and_never_runs(monkeypatch, tmp_path) -> None:
    isolated = ResearchService(data_dir=tmp_path, enable_agent_runtime=False)
    monkeypatch.setattr(research_router, "service", isolated)
    try:
        created = _research(isolated)
        client = TestClient(app)
        config = client.get(f"/api/researches/{created['id']}/optimization-config").json()
        payload = {
            "type": "apply_research_state",
            "goal": "在体积分数约束下降低柔度",
            "hypothesis": "提高惩罚因子会降低灰度率",
            "optimizationConfig": config,
            "changedFields": ["goal", "hypothesis", "optimizationConfig"],
            "rationale": "由当前证据提出的受限建议",
            "messageId": "msg-agent-action",
        }
        response = client.post(f"/api/researches/{created['id']}/apply-suggestion", json=payload)
        assert response.status_code == 200
        assert response.json()["research"]["goal"] == payload["goal"]
        assert response.json()["research"]["hypothesis"] == payload["hypothesis"]
        assert response.json()["optimizationConfig"] == config
        events = isolated.store.list_events(created["id"])
        assert events[-1]["kind"] == "AGENT_SUGGESTION_APPROVED"
        assert events[-1]["payload"]["agent_message_id"] == "msg-agent-action"
        assert isolated.get_research(created["id"])["experiments"] == []

        rejected = client.post(
            f"/api/researches/{created['id']}/apply-suggestion",
            json=payload | {"command": "run matlab now"},
        )
        assert rejected.status_code == 422
    finally:
        isolated.close()


def test_research_action_is_removed_from_visible_reply() -> None:
    content = (
        "建议补充假设。"
        "<topoptpilot-research-action>"
        '{"type":"apply_research_state","hypothesis":"滤波半径影响灰度率",'
        '"changedFields":["hypothesis"]}'
        "</topoptpilot-research-action>"
    )
    reply, actions = research_router._research_action(content)
    assert reply == "建议补充假设。"
    assert actions[0]["type"] == "apply_research_state"
    assert "topoptpilot-research-action" not in reply