"""Local JSONL conversations and content-addressed image attachments."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

router = APIRouter(prefix="/api/conversations", tags=["conversations"])
_ALLOWED_MEDIA = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/svg+xml": ".svg", "application/pdf": ".pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx", "text/plain": ".txt", "text/csv": ".csv"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_lock = threading.RLock()
_EMPTY_TEST_TITLE = re.compile(
    r"(?:测试|演示|样例|(?<![A-Za-z0-9])(?:test|demo)(?![A-Za-z0-9]))",
    re.IGNORECASE,
)


def _root() -> Path:
    configured = os.environ.get("IDESKTOP_V2_DATA_DIR") or os.environ.get("TOPPILOT_DATA_DIR")
    base = Path(configured).expanduser().resolve() if configured else Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")
    ) / "iDeskTopV2"
    value = base / "conversations"
    value.mkdir(parents=True, exist_ok=True)
    (value / "items").mkdir(exist_ok=True)
    (value / "attachments").mkdir(exist_ok=True)
    return value


def _atomic_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _index() -> list[dict[str, Any]]:
    path = _root() / "index.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def _save_index(items: list[dict[str, Any]]) -> None:
    _atomic_json(_root() / "index.json", items)


def _conversation_dir(conversation_id: str) -> Path:
    if not re.fullmatch(r"conv-[0-9a-f]{32}", conversation_id):
        raise KeyError(conversation_id)
    path = (_root() / "items" / conversation_id).resolve()
    if (_root() / "items").resolve() not in path.parents:
        raise KeyError(conversation_id)
    return path


def _meta(conversation_id: str) -> dict[str, Any]:
    path = _conversation_dir(conversation_id) / "meta.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise KeyError(conversation_id) from exc
    if not isinstance(value, dict) or value.get("id") != conversation_id:
        raise KeyError(conversation_id)
    return value


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["engineering", "research"]
    ownerId: str = Field(min_length=1, max_length=160)
    title: str = Field(default="新对话", min_length=1, max_length=120)


class ConversationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "system", "progress"]
    content: str = Field(min_length=1, max_length=120_000)
    attachmentIds: list[str] = Field(default_factory=list, max_length=4)
    source: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=80)


class AttachmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fileName: str = Field(min_length=1, max_length=255)
    mediaType: str
    dataBase64: str = Field(min_length=1, max_length=15_000_000)

    @field_validator("mediaType")
    @classmethod
    def media_type(cls, value: str) -> str:
        if value not in _ALLOWED_MEDIA:
            raise ValueError("仅支持图片、SVG、PDF、Word、Excel 和文本附件")
        return value


def list_conversations(scope: str | None = None, owner_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        items = _index()
    if scope:
        items = [item for item in items if item.get("scope") == scope]
    if owner_id:
        items = [item for item in items if item.get("ownerId") == owner_id]
    return sorted(items, key=lambda item: float(item.get("updatedAt", 0)), reverse=True)


def create_conversation(request: ConversationCreate) -> dict[str, Any]:
    now = time.time()
    item = {
        "id": f"conv-{uuid.uuid4().hex}", "scope": request.scope,
        "ownerId": request.ownerId, "title": request.title.strip(),
        "createdAt": now, "updatedAt": now,
    }
    with _lock:
        directory = _conversation_dir(item["id"])
        directory.mkdir(parents=True, exist_ok=False)
        _atomic_json(directory / "meta.json", item)
        (directory / "messages.jsonl").touch()
        items = _index()
        items.append(item)
        _save_index(items)
    return item


def cleanup_empty_test_conversations_once() -> list[str]:
    """Remove only legacy zero-message test/demo conversations once per data directory."""
    root = _root()
    marker = root / ".cleanup-empty-test-v1"
    if marker.exists():
        return []
    removed: list[str] = []
    with _lock:
        retained: list[dict[str, Any]] = []
        for item in _index():
            conversation_id = str(item.get("id") or "")
            title = str(item.get("title") or "")
            if not _EMPTY_TEST_TITLE.search(title):
                retained.append(item)
                continue
            try:
                if read_messages(conversation_id):
                    retained.append(item)
                    continue
                directory = _conversation_dir(conversation_id)
                for path in directory.iterdir():
                    if path.is_file():
                        path.unlink()
                directory.rmdir()
                removed.append(conversation_id)
            except (KeyError, OSError):
                retained.append(item)
        _save_index(retained)
        marker.write_text(json.dumps({"version": 1, "removed": removed}, ensure_ascii=False), encoding="utf-8")
    return removed


def append_message(conversation_id: str, request: MessageCreate) -> dict[str, Any]:
    meta = _meta(conversation_id)
    attachments = []
    for attachment_id in request.attachmentIds:
        path = _attachment_path(attachment_id)
        attachments.append({
            "id": attachment_id,
            "mediaType": _attachment_media(path),
            "sizeBytes": path.stat().st_size,
        })
    message = {
        "id": f"msg-{uuid.uuid4().hex}", "seq": len(read_messages(conversation_id)) + 1,
        "role": request.role, "content": request.content,
        "attachmentIds": list(request.attachmentIds), "attachments": attachments,
        "source": request.source, "status": request.status, "createdAt": time.time(),
    }
    with _lock:
        with (_conversation_dir(conversation_id) / "messages.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        meta["updatedAt"] = message["createdAt"]
        _atomic_json(_conversation_dir(conversation_id) / "meta.json", meta)
        items = [meta if item.get("id") == conversation_id else item for item in _index()]
        _save_index(items)
    return message


def read_messages(conversation_id: str, after_seq: int = 0) -> list[dict[str, Any]]:
    _meta(conversation_id)
    path = _conversation_dir(conversation_id) / "messages.jsonl"
    messages: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and int(message.get("seq", 0)) > after_seq:
            messages.append(message)
    return messages


def save_attachment(request: AttachmentCreate) -> dict[str, Any]:
    try:
        raw = base64.b64decode(request.dataBase64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("附件 Base64 数据无效") from exc
    if not raw or len(raw) > _MAX_IMAGE_BYTES:
        raise ValueError("单个附件必须小于等于 10 MB")
    signatures = {
        "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
        "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
        "image/svg+xml": b"<svg" in raw[:1024].lower(),
        "application/pdf": raw.startswith(b"%PDF-"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": raw.startswith(b"PK"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": raw.startswith(b"PK"),
        "text/plain": b"\x00" not in raw[:4096],
        "text/csv": b"\x00" not in raw[:4096],
    }
    if not signatures[request.mediaType]:
        raise ValueError("附件内容与媒体类型不匹配")
    digest = hashlib.sha256(raw).hexdigest()
    attachment_id = f"att-{digest}"
    path = _root() / "attachments" / f"{attachment_id}{_ALLOWED_MEDIA[request.mediaType]}"
    with _lock:
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(raw)
            temporary.replace(path)
        metadata = {
            "id": attachment_id, "fileName": Path(request.fileName).name,
            "mediaType": request.mediaType, "sizeBytes": len(raw), "sha256": digest,
        }
        _atomic_json(path.with_suffix(path.suffix + ".json"), metadata)
    return metadata


def _attachment_path(attachment_id: str) -> Path:
    if not re.fullmatch(r"att-[0-9a-f]{64}", attachment_id):
        raise KeyError(attachment_id)
    matches = [path for path in (_root() / "attachments").glob(f"{attachment_id}.*") if path.suffix in set(_ALLOWED_MEDIA.values())]
    if len(matches) != 1:
        raise KeyError(attachment_id)
    return matches[0]


def attachment_for_ai(attachment_id: str) -> dict[str, str]:
    path = _attachment_path(attachment_id)
    media = _attachment_media(path)
    if media in {"image/png", "image/jpeg", "image/webp"}:
        return {"kind": "image", "mediaType": media, "content": attachment_data_url(attachment_id), "fileName": path.name}
    if media == "application/pdf":
        import fitz
        with fitz.open(path) as document:
            text = "\n".join(page.get_text() for page in document)
    elif path.suffix in {".docx", ".xlsx"}:
        import zipfile
        from xml.etree import ElementTree
        chunks: list[str] = []
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".xml") and ("word/" in name or "xl/" in name)]
            for name in names[:80]:
                try:
                    root = ElementTree.fromstring(archive.read(name))
                    chunks.extend(value.strip() for value in root.itertext() if value.strip())
                except (ValueError, ElementTree.ParseError):
                    continue
        text = "\n".join(chunks)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {"kind": "document", "mediaType": media, "content": text[:120_000], "fileName": path.name}


def attachment_data_url(attachment_id: str) -> str:
    path = _attachment_path(attachment_id)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_attachment_media(path)};base64,{encoded}"

def _attachment_media(path: Path) -> str:
    return {suffix: media for media, suffix in _ALLOWED_MEDIA.items()}[path.suffix]


@router.get("")
def conversation_list(scope: str | None = None, owner_id: str | None = None):
    return list_conversations(scope, owner_id)


@router.post("", status_code=201)
def conversation_create(request: ConversationCreate):
    return create_conversation(request)


@router.patch("/{conversation_id}")
def conversation_patch(conversation_id: str, request: ConversationPatch):
    try:
        item = _meta(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    item["title"] = request.title.strip()
    item["updatedAt"] = time.time()
    with _lock:
        _atomic_json(_conversation_dir(conversation_id) / "meta.json", item)
        _save_index([item if value.get("id") == conversation_id else value for value in _index()])
    return item


@router.delete("/{conversation_id}")
def conversation_delete(conversation_id: str):
    try:
        directory = _conversation_dir(conversation_id)
        _meta(conversation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    with _lock:
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
        directory.rmdir()
        _save_index([item for item in _index() if item.get("id") != conversation_id])
    return {"deleted": True, "id": conversation_id}


@router.get("/{conversation_id}/messages")
def conversation_messages(conversation_id: str, after_seq: int = 0):
    try:
        return read_messages(conversation_id, after_seq)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc


@router.post("/{conversation_id}/messages", status_code=201)
def conversation_message_create(conversation_id: str, request: MessageCreate):
    try:
        return append_message(conversation_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation or attachment not found") from exc


@router.post("/{conversation_id}/attachments", status_code=201)
def conversation_attachment_create(conversation_id: str, request: AttachmentCreate):
    try:
        _meta(conversation_id)
        return save_attachment(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/attachments/{attachment_id}")
def conversation_attachment_get(attachment_id: str):
    try:
        path = _attachment_path(attachment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="attachment not found") from exc
    return FileResponse(path, media_type=_attachment_media(path), filename=path.name)
