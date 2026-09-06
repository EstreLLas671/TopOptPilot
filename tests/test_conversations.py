import base64
from pathlib import Path

from fastapi.testclient import TestClient

from topoptpilot_desktop.api.app import app
from topoptpilot_desktop.conversations import (
    ConversationCreate,
    MessageCreate,
    append_message,
    attachment_for_ai,
    cleanup_empty_test_conversations_once,
    create_conversation,
    list_conversations,
)


PNG_1X1 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
).decode("ascii")


def test_project_conversation_and_attachment_round_trip(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    created = client.post(
        "/api/conversations",
        json={"scope": "engineering", "ownerId": "project-a", "title": "材料讨论"},
    )
    assert created.status_code == 201
    conversation_id = created.json()["id"]

    uploaded = client.post(
        f"/api/conversations/{conversation_id}/attachments",
        json={"fileName": "case.png", "mediaType": "image/png", "dataBase64": PNG_1X1},
    )
    assert uploaded.status_code == 201
    attachment_id = uploaded.json()["id"]
    message = client.post(
        f"/api/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "解释这张图", "attachmentIds": [attachment_id]},
    )
    assert message.status_code == 201
    assert message.json()["attachments"][0]["mediaType"] == "image/png"

    listing = client.get("/api/conversations", params={"scope": "engineering", "owner_id": "project-a"})
    assert [item["id"] for item in listing.json()] == [conversation_id]
    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert messages[0]["content"] == "解释这张图"
    assert "dataBase64" not in str(messages)


def test_rejects_mismatched_image_content(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    conversation_id = client.post(
        "/api/conversations",
        json={"scope": "research", "ownerId": "R-001", "title": "研究对话"},
    ).json()["id"]
    response = client.post(
        f"/api/conversations/{conversation_id}/attachments",
        json={
            "fileName": "fake.png",
            "mediaType": "image/png",
            "dataBase64": base64.b64encode(b"not an image").decode("ascii"),
        },
    )
    assert response.status_code == 422

def test_document_attachments_are_extracted_for_ai_only_after_upload(monkeypatch, tmp_path: Path) -> None:
    import io
    import zipfile

    import fitz

    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    client = TestClient(app)
    conversation_id = client.post(
        "/api/conversations",
        json={"scope": "engineering", "ownerId": "project-docs", "title": "文档讨论"},
    ).json()["id"]

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "TopOptPilot PDF evidence")
    pdf_bytes = document.tobytes()
    document.close()

    def office_zip(name: str, xml: str) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr(name, xml)
        return stream.getvalue()

    cases = [
        ("evidence.pdf", "application/pdf", pdf_bytes, "TopOptPilot PDF evidence"),
        ("notes.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", office_zip("word/document.xml", "<w:document xmlns:w='urn:w'><w:t>DOCX material</w:t></w:document>"), "DOCX material"),
        ("table.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", office_zip("xl/sharedStrings.xml", "<sst><si><t>XLSX parameter</t></si></sst>"), "XLSX parameter"),
        ("shape.svg", "image/svg+xml", b"<svg><text>SVG geometry</text></svg>", "SVG geometry"),
        ("readme.txt", "text/plain", b"plain attachment text", "plain attachment text"),
    ]
    for file_name, media_type, raw, expected in cases:
        response = client.post(
            f"/api/conversations/{conversation_id}/attachments",
            json={
                "fileName": file_name,
                "mediaType": media_type,
                "dataBase64": base64.b64encode(raw).decode("ascii"),
            },
        )
        assert response.status_code == 201, response.text
        extracted = attachment_for_ai(response.json()["id"])
        assert extracted["kind"] == "document"
        assert expected in extracted["content"]


def test_cleanup_only_removes_empty_explicit_test_conversations_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TOPOPTPILOT_DATA_DIR", str(tmp_path))
    empty_test = create_conversation(ConversationCreate(scope="engineering", ownerId="P1", title="测试空白"))
    empty_demo = create_conversation(ConversationCreate(scope="research", ownerId="R1", title="demo empty"))
    populated_test = create_conversation(ConversationCreate(scope="research", ownerId="R1", title="测试但有消息"))
    ordinary = create_conversation(ConversationCreate(scope="engineering", ownerId="P1", title="普通空白"))
    embedded_word = create_conversation(ConversationCreate(scope="engineering", ownerId="P1", title="contest analysis"))
    append_message(populated_test["id"], MessageCreate(role="user", content="保留这条真实消息"))

    removed = cleanup_empty_test_conversations_once()
    assert set(removed) == {empty_test["id"], empty_demo["id"]}
    remaining = {item["id"] for item in list_conversations()}
    assert populated_test["id"] in remaining
    assert ordinary["id"] in remaining
    assert embedded_word["id"] in remaining
    assert cleanup_empty_test_conversations_once() == []
