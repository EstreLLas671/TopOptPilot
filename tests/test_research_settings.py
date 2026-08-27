from __future__ import annotations

from fastapi.testclient import TestClient

from idesktop_v2.api.app import app
from idesktop_v2 import research_router
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