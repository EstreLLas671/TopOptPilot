"""Persistent engineering comparison schemes backed by restored real runs."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from idesktop_v2.artifacts.models import RunStatus
from idesktop_v2.engineering.runs import _data_root, manager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ComparisonSchemeStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    @staticmethod
    def _db_path() -> Path:
        path = _data_root().parent / "engineering.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path(), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """CREATE TABLE IF NOT EXISTS comparison_schemes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                run_id TEXT NOT NULL,
                config_digest TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_comparison_created ON comparison_schemes(created_at DESC)"
        )
        connection.commit()
        return connection

    @staticmethod
    def _integrity(record) -> tuple[str, list[str]]:
        failures: list[str] = []
        root = record.run_dir.resolve()
        for reference in [*record.files, *record.snapshots]:
            target = (root / Path(reference.relative_path)).resolve()
            if root not in target.parents or not target.is_file():
                failures.append(reference.relative_path)
                continue
            if target.stat().st_size != reference.size_bytes:
                failures.append(reference.relative_path)
                continue
            if hashlib.sha256(target.read_bytes()).hexdigest() != reference.sha256:
                failures.append(reference.relative_path)
        return ("verified" if not failures else "failed", failures)

    def _detail(self, row: sqlite3.Row) -> dict[str, Any]:
        record = manager.get(row["run_id"])
        if record is None:
            return {
                "id": row["id"], "name": row["name"], "runId": row["run_id"],
                "configDigest": row["config_digest"], "createdAt": row["created_at"],
                "config": {}, "run": None, "integrity": "missing", "integrityFailures": ["run-manifest.json"],
            }
        integrity, failures = self._integrity(record)
        return {
            "id": row["id"], "name": row["name"], "runId": row["run_id"],
            "configDigest": row["config_digest"], "createdAt": row["created_at"],
            "config": record.task, "run": record.public(), "integrity": integrity,
            "integrityFailures": failures,
        }

    def list(self) -> list[dict[str, Any]]:
        with self._lock, closing(self._connection()) as db:
            rows = db.execute("SELECT * FROM comparison_schemes ORDER BY created_at DESC").fetchall()
        return [self._detail(row) for row in rows]

    def get(self, scheme_id: str) -> dict[str, Any] | None:
        with self._lock, closing(self._connection()) as db:
            row = db.execute("SELECT * FROM comparison_schemes WHERE id=?", (scheme_id,)).fetchone()
        return self._detail(row) if row else None

    def create(self, run_id: str, name: str | None = None) -> dict[str, Any]:
        record = manager.get(run_id)
        if record is None:
            raise KeyError(run_id)
        if record.status is not RunStatus.COMPLETED:
            raise ValueError("只有已完成的真实运行可以保存为对比方案")
        if record.provenance.get("resultKind") != "solver" or not record.files:
            raise ValueError("运行缺少真实求解器来源或制品，不能保存为对比方案")
        integrity, failures = self._integrity(record)
        if integrity != "verified":
            raise ValueError("运行制品完整性校验失败：" + "、".join(failures[:5]))
        scheme_id = "scheme-" + uuid.uuid4().hex
        title = (name or "").strip() or "方案 " + datetime.now().strftime("%Y-%m-%d %H:%M")
        with self._lock, closing(self._connection()) as db:
            db.execute(
                "INSERT INTO comparison_schemes(id,name,run_id,config_digest,created_at) VALUES(?,?,?,?,?)",
                (scheme_id, title[:120], run_id, record.config_digest, _utc_now()),
            )
            db.commit()
        value = self.get(scheme_id)
        assert value is not None
        return value

    def delete(self, scheme_id: str) -> bool:
        with self._lock, closing(self._connection()) as db:
            cursor = db.execute("DELETE FROM comparison_schemes WHERE id=?", (scheme_id,))
            db.commit()
        return cursor.rowcount > 0


comparison_schemes = ComparisonSchemeStore()
