"""SQLite-backed source of truth for research records.

UI session data intentionally does not live here. This store owns projects,
experiments, decisions and the append-only activity stream.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ResearchStateStore:
    def __init__(self, db_path: str | Path = "topoptpilot/storage/research.db"):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                    constraints_json TEXT NOT NULL, mode TEXT NOT NULL,
                    status TEXT NOT NULL, budget_total INTEGER NOT NULL,
                    budget_used INTEGER NOT NULL DEFAULT 0,
                    locks_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY, research_id TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, purpose TEXT NOT NULL,
                    fidelity TEXT NOT NULL, mesh_level TEXT NOT NULL,
                    backend TEXT NOT NULL, parameters_json TEXT NOT NULL,
                    warm_start TEXT, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                    current_iteration INTEGER NOT NULL DEFAULT 0,
                    run_id TEXT, safety TEXT NOT NULL DEFAULT 'LOW',
                    result_json TEXT, error TEXT, created_at TEXT NOT NULL,
                    started_at TEXT, completed_at TEXT,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, research_id TEXT NOT NULL,
                    experiment_id TEXT, kind TEXT NOT NULL, title TEXT NOT NULL,
                    body TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY, research_id TEXT NOT NULL,
                    experiment_id TEXT, intent TEXT NOT NULL, reason TEXT NOT NULL,
                    proposal_json TEXT NOT NULL, risk TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
                CREATE INDEX IF NOT EXISTS idx_exp_research ON experiments(research_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_event_research ON events(research_id, id);
                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY, research_id TEXT NOT NULL, intent TEXT NOT NULL,
                    purpose TEXT NOT NULL, fidelity TEXT NOT NULL, backend TEXT NOT NULL,
                    parameters_json TEXT NOT NULL, estimated_cost REAL NOT NULL,
                    risk TEXT NOT NULL, safety_status TEXT NOT NULL,
                    approval_required INTEGER NOT NULL DEFAULT 0, source_experiment TEXT,
                    controlled_factors_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL,
                    experiment_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
                CREATE TABLE IF NOT EXISTS memory_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, research_id TEXT NOT NULL,
                    level TEXT NOT NULL, content_json TEXT NOT NULL, created_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
                CREATE TABLE IF NOT EXISTS agent_sessions (
                    research_id TEXT PRIMARY KEY, session_id TEXT, session_file TEXT,
                    status TEXT NOT NULL DEFAULT 'OFFLINE', context_usage REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(research_id) REFERENCES research(id)
                );
            """)
            self._ensure_columns(db, "research", {
                "budgets_json": "TEXT NOT NULL DEFAULT '{}'",
                "geometry_json": "TEXT NOT NULL DEFAULT '{}'",
                "material_json": "TEXT NOT NULL DEFAULT '{}'",
                "loads_json": "TEXT NOT NULL DEFAULT '[]'",
                "boundary_conditions_json": "TEXT NOT NULL DEFAULT '{}'",
                "hypothesis": "TEXT",
                "current_question": "TEXT",
                "current_round": "INTEGER NOT NULL DEFAULT 0",
                "termination_reason": "TEXT",
                "locale": "TEXT NOT NULL DEFAULT 'zh-CN'",
            })
            self._ensure_columns(db, "experiments", {
                "proposal_id": "TEXT",
                "intent": "TEXT NOT NULL DEFAULT 'MANUAL'",
                "cached": "INTEGER NOT NULL DEFAULT 0",
            })
            self._ensure_columns(db, "agent_sessions", {
                "stream_text": "TEXT NOT NULL DEFAULT ''",
                "last_error": "TEXT",
            })

    @staticmethod
    def _ensure_columns(db: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _decode(row: sqlite3.Row | None, json_fields: Iterable[str]) -> dict | None:
        if row is None:
            return None
        value = dict(row)
        for field in json_fields:
            raw = value.pop(f"{field}_json", None)
            value[field] = json.loads(raw or "{}")
        return value

    def create_research(self, data: dict[str, Any]) -> dict:
        now = utc_now()
        with self._lock, self.connection() as db:
            db.execute("""INSERT INTO research
                (id,name,goal,constraints_json,mode,status,budget_total,budget_used,locks_json,
                 created_at,updated_at,budgets_json,geometry_json,material_json,loads_json,
                 boundary_conditions_json,hypothesis,current_question,current_round,locale)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["name"], data["goal"], json.dumps(data["constraints"]),
                 data["mode"], "READY", data["budget_total"], 0, "{}", now, now,
                 json.dumps(data.get("budgets", {})), json.dumps(data.get("geometry", {})),
                 json.dumps(data.get("material", {})), json.dumps(data.get("loads", [])),
                 json.dumps(data.get("boundary_conditions", {})), data.get("hypothesis"),
                 None, 0, data.get("locale", "zh-CN")))
        return self.get_research(data["id"])

    def list_research(self) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM research ORDER BY updated_at DESC").fetchall()
        return [self._decode(row, ("constraints", "locks", "budgets", "geometry", "material",
                                   "loads", "boundary_conditions")) for row in rows]

    def get_research(self, research_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM research WHERE id=?", (research_id,)).fetchone()
        return self._decode(row, ("constraints", "locks", "budgets", "geometry", "material",
                                  "loads", "boundary_conditions"))

    def update_research(self, research_id: str, **fields: Any) -> dict:
        allowed = {"name", "goal", "mode", "status", "budget_total", "budget_used",
                   "hypothesis", "current_question", "current_round", "termination_reason", "locale"}
        assignments, values = [], []
        for name, value in fields.items():
            if name in allowed:
                assignments.append(f"{name}=?")
                values.append(value)
        if assignments:
            assignments.append("updated_at=?")
            values.extend((utc_now(), research_id))
            with self._lock, self.connection() as db:
                db.execute(f"UPDATE research SET {', '.join(assignments)} WHERE id=?", values)
        return self.get_research(research_id)

    def update_research_json(self, research_id: str, **fields: Any) -> dict:
        allowed = {"constraints", "budgets", "geometry", "material", "loads", "boundary_conditions"}
        assignments, values = [], []
        for name, value in fields.items():
            if name in allowed:
                assignments.append(f"{name}_json=?")
                values.append(json.dumps(value, default=_json_default))
        if assignments:
            assignments.append("updated_at=?")
            values.extend((utc_now(), research_id))
            with self._lock, self.connection() as db:
                db.execute(f"UPDATE research SET {', '.join(assignments)} WHERE id=?", values)
        return self.get_research(research_id)

    def set_locks(self, research_id: str, locks: dict[str, Any]) -> None:
        with self._lock, self.connection() as db:
            db.execute("UPDATE research SET locks_json=?, updated_at=? WHERE id=?",
                       (json.dumps(locks), utc_now(), research_id))

    def create_experiment(self, data: dict[str, Any]) -> dict:
        now = utc_now()
        with self._lock, self.connection() as db:
            ordinal = db.execute(
                "SELECT COALESCE(MAX(ordinal),0)+1 FROM experiments WHERE research_id=?",
                (data["research_id"],),
            ).fetchone()[0]
            db.execute("""INSERT INTO experiments
                (id,research_id,ordinal,purpose,fidelity,mesh_level,backend,parameters_json,
                 warm_start,status,safety,created_at,proposal_id,intent) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["research_id"], ordinal, data["purpose"], data["fidelity"],
                 data["mesh_level"], data["backend"], json.dumps(data["parameters"]),
                 data.get("warm_start"), data["status"], data.get("safety", "LOW"), now,
                 data.get("proposal_id"), data.get("intent", "MANUAL")))
        return self.get_experiment(data["id"])

    def get_experiment(self, experiment_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM experiments WHERE id=?", (experiment_id,)).fetchone()
        return self._decode(row, ("parameters", "result"))

    def list_experiments(self, research_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM experiments WHERE research_id=? ORDER BY ordinal", (research_id,)
            ).fetchall()
        return [self._decode(row, ("parameters", "result")) for row in rows]

    def update_experiment(self, experiment_id: str, **fields: Any) -> dict:
        allowed = {"status", "progress", "current_iteration", "run_id", "safety",
                   "error", "started_at", "completed_at", "purpose", "fidelity", "proposal_id",
                   "intent", "cached"}
        assignments, values = [], []
        for name, value in fields.items():
            if name in allowed:
                assignments.append(f"{name}=?")
                values.append(value)
        if "parameters" in fields:
            assignments.append("parameters_json=?")
            values.append(json.dumps(fields["parameters"]))
        if "result" in fields:
            assignments.append("result_json=?")
            values.append(json.dumps(fields["result"], default=_json_default))
        if assignments:
            values.append(experiment_id)
            with self._lock, self.connection() as db:
                db.execute(f"UPDATE experiments SET {', '.join(assignments)} WHERE id=?", values)
        return self.get_experiment(experiment_id)

    def append_event(self, research_id: str, kind: str, title: str, body: str,
                     experiment_id: str | None = None, payload: dict | None = None) -> dict:
        with self._lock, self.connection() as db:
            cursor = db.execute("""INSERT INTO events
                (research_id,experiment_id,kind,title,body,payload_json,created_at)
                VALUES (?,?,?,?,?,?,?)""",
                (research_id, experiment_id, kind, title, body,
                 json.dumps(payload or {}, default=_json_default), utc_now()))
            event_id = cursor.lastrowid
            row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return self._decode(row, ("payload",))

    def list_events(self, research_id: str, limit: int = 300) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("""SELECT * FROM events WHERE research_id=?
                ORDER BY id DESC LIMIT ?""", (research_id, limit)).fetchall()
        return [self._decode(row, ("payload",)) for row in reversed(rows)]

    def create_decision(self, data: dict[str, Any]) -> dict:
        with self._lock, self.connection() as db:
            db.execute("""INSERT INTO decisions
                (id,research_id,experiment_id,intent,reason,proposal_json,risk,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["research_id"], data.get("experiment_id"), data["intent"],
                 data["reason"], json.dumps(data["proposal"]), data["risk"],
                 data["status"], utc_now()))
        return self.get_decision(data["id"])

    def get_decision(self, decision_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
        return self._decode(row, ("proposal",))

    def list_decisions(self, research_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM decisions WHERE research_id=? ORDER BY created_at",
                              (research_id,)).fetchall()
        return [self._decode(row, ("proposal",)) for row in rows]

    def resolve_decision(self, decision_id: str, status: str) -> dict:
        with self._lock, self.connection() as db:
            db.execute("UPDATE decisions SET status=?, resolved_at=? WHERE id=?",
                       (status, utc_now(), decision_id))
        return self.get_decision(decision_id)

    def update_decision(self, decision_id: str, *, proposal: dict | None = None,
                        risk: str | None = None, reason: str | None = None) -> dict:
        assignments, values = [], []
        if proposal is not None:
            assignments.append("proposal_json=?"); values.append(json.dumps(proposal))
        if risk is not None:
            assignments.append("risk=?"); values.append(risk)
        if reason is not None:
            assignments.append("reason=?"); values.append(reason)
        if assignments:
            values.append(decision_id)
            with self._lock, self.connection() as db:
                db.execute(f"UPDATE decisions SET {', '.join(assignments)} WHERE id=?", values)
        return self.get_decision(decision_id)

    def create_proposal(self, data: dict[str, Any]) -> dict:
        now = utc_now()
        with self._lock, self.connection() as db:
            db.execute("""INSERT INTO proposals
                (id,research_id,intent,purpose,fidelity,backend,parameters_json,estimated_cost,
                 risk,safety_status,approval_required,source_experiment,controlled_factors_json,
                 status,experiment_id,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (data["id"], data["research_id"], data["intent"], data["purpose"],
                 data["fidelity"], data["backend"], json.dumps(data["parameters"]),
                 data["estimated_cost"], data["risk"], data["safety_status"],
                 int(data.get("approval_required", False)), data.get("source_experiment"),
                 json.dumps(data.get("controlled_factors", [])), data.get("status", "PREVIEW"),
                 data.get("experiment_id"), now, now))
        return self.get_proposal(data["id"])

    def get_proposal(self, proposal_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        return self._decode(row, ("parameters", "controlled_factors"))

    def list_proposals(self, research_id: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM proposals WHERE research_id=? ORDER BY created_at",
                              (research_id,)).fetchall()
        return [self._decode(row, ("parameters", "controlled_factors")) for row in rows]

    def update_proposal(self, proposal_id: str, **fields: Any) -> dict:
        allowed = {"status", "experiment_id", "safety_status"}
        assignments, values = [], []
        for name, value in fields.items():
            if name in allowed:
                assignments.append(f"{name}=?")
                values.append(value)
        if assignments:
            assignments.append("updated_at=?")
            values.extend((utc_now(), proposal_id))
            with self._lock, self.connection() as db:
                db.execute(f"UPDATE proposals SET {', '.join(assignments)} WHERE id=?", values)
        return self.get_proposal(proposal_id)

    def save_memory_snapshot(self, research_id: str, level: str, content: dict) -> None:
        with self._lock, self.connection() as db:
            db.execute("INSERT INTO memory_snapshots (research_id,level,content_json,created_at) VALUES (?,?,?,?)",
                       (research_id, level, json.dumps(content, default=_json_default), utc_now()))

    def latest_memory_snapshot(self, research_id: str, level: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("""SELECT content_json FROM memory_snapshots
                WHERE research_id=? AND level=? ORDER BY id DESC LIMIT 1""",
                (research_id, level)).fetchone()
        return json.loads(row[0]) if row else None

    def upsert_agent_session(self, research_id: str, **fields: Any) -> dict:
        current = self.get_agent_session(research_id) or {}
        value = {
            "session_id": fields.get("session_id", current.get("session_id")),
            "session_file": fields.get("session_file", current.get("session_file")),
            "status": fields.get("status", current.get("status", "OFFLINE")),
            "context_usage": fields.get("context_usage", current.get("context_usage", 0.0)),
            "stream_text": fields.get("stream_text", current.get("stream_text", "")),
            "last_error": fields.get("last_error", current.get("last_error")),
        }
        with self._lock, self.connection() as db:
            db.execute("""INSERT INTO agent_sessions
                (research_id,session_id,session_file,status,context_usage,stream_text,last_error,updated_at)
                VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(research_id) DO UPDATE SET
                session_id=excluded.session_id,session_file=excluded.session_file,
                status=excluded.status,context_usage=excluded.context_usage,
                stream_text=excluded.stream_text,last_error=excluded.last_error,
                updated_at=excluded.updated_at""",
                (research_id, value["session_id"], value["session_file"], value["status"],
                 value["context_usage"], value["stream_text"], value["last_error"], utc_now()))
        return self.get_agent_session(research_id)

    def get_agent_session(self, research_id: str) -> dict | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM agent_sessions WHERE research_id=?", (research_id,)).fetchone()
        return dict(row) if row else None


def _json_default(value: Any):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)
