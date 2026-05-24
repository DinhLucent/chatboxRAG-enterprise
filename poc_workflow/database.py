from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .config import VALID_FEEDBACK
from .utils import utc_now

VALID_INCIDENT_SEVERITIES = {"info", "warning", "error", "critical"}
VALID_INCIDENT_STATUSES = {"open", "resolved", "ignored"}


class QualityDatabase:
    def __init__(self, root: Path):
        self.path = root / "data" / "poc_quality.db"

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS query_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    user_id TEXT,
                    retrieved_doc_ids TEXT NOT NULL,
                    answer_has_citation INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    feedback TEXT,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_gaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    suspected_category TEXT,
                    suggested_owner TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    doc_id TEXT,
                    version TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    severity TEXT NOT NULL,
                    component TEXT NOT NULL,
                    title TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    context TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                )
                """
            )

    def log_ingestion(
        self,
        status: str,
        doc_id: str | None = None,
        version: str | None = None,
        error_message: str | None = None,
        run_id: str | None = None,
    ) -> str:
        self.init()
        run_id = run_id or str(uuid.uuid4())
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_runs (run_id, doc_id, version, status, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (run_id, doc_id, version, status, error_message, utc_now()),
            )
        return run_id

    def log_query(
        self,
        query: str,
        user_id: str | None,
        retrieved_doc_ids: list[str],
        answer_has_citation: bool,
        latency_ms: int,
        answer: str,
    ) -> int:
        self.init()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO query_logs (
                    query, user_id, retrieved_doc_ids, answer_has_citation, latency_ms, answer, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query,
                    user_id,
                    json.dumps(retrieved_doc_ids, ensure_ascii=False),
                    1 if answer_has_citation else 0,
                    latency_ms,
                    answer,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def set_feedback(self, log_id: int, feedback: str) -> dict[str, Any]:
        if feedback not in VALID_FEEDBACK:
            raise ValueError(f"Unsupported feedback: {feedback}")
        self.init()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM query_logs WHERE id = ?", (log_id,)).fetchone()
            if not row:
                raise ValueError(f"Query log not found: {log_id}")
            conn.execute("UPDATE query_logs SET feedback = ? WHERE id = ?", (feedback, log_id))
            return dict(row)

    def create_gap(
        self,
        query: str,
        reason: str,
        suspected_category: str | None = None,
        suggested_owner: str | None = "Phong Ky thuat",
        status: str = "open",
    ) -> int:
        self.init()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO knowledge_gaps (
                    query, reason, suspected_category, suggested_owner, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (query, reason, suspected_category, suggested_owner, status, utc_now()),
            )
            return int(cursor.lastrowid)

    def create_incident(
        self,
        severity: str,
        component: str,
        title: str,
        detail: str,
        context: dict[str, Any] | None = None,
        status: str = "open",
    ) -> int:
        if severity not in VALID_INCIDENT_SEVERITIES:
            raise ValueError(f"Unsupported incident severity: {severity}")
        if status not in VALID_INCIDENT_STATUSES:
            raise ValueError(f"Unsupported incident status: {status}")
        self.init()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO incidents (
                    severity, component, title, detail, context, status, created_at, resolved_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    severity,
                    component,
                    title,
                    detail,
                    json.dumps(context or {}, ensure_ascii=False),
                    status,
                    utc_now(),
                    None,
                ),
            )
            return int(cursor.lastrowid)

    def list_gaps(self, status: str | None = None) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM knowledge_gaps WHERE status = ? ORDER BY id DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM knowledge_gaps ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def list_queries(self) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM query_logs ORDER BY id DESC").fetchall()]

    def list_ingestion_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            ]

    def list_incidents(self, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 500))
        with self.connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM incidents WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM incidents ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [self._incident_row(row) for row in rows]

    def resolve_incident(self, incident_id: int, status: str = "resolved") -> dict[str, Any]:
        if status not in {"resolved", "ignored"}:
            raise ValueError("Incident can only be resolved or ignored")
        self.init()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            if not row:
                raise ValueError(f"Incident not found: {incident_id}")
            conn.execute(
                "UPDATE incidents SET status = ?, resolved_at = ? WHERE id = ?",
                (status, utc_now(), incident_id),
            )
            updated = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            return self._incident_row(updated)

    def stats(self) -> dict[str, Any]:
        self.init()
        with self.connect() as conn:
            query_count = conn.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
            gap_count = conn.execute(
                "SELECT COUNT(*) FROM knowledge_gaps WHERE status = 'open'"
            ).fetchone()[0]
            failed_ingestions = conn.execute(
                "SELECT COUNT(*) FROM ingestion_runs WHERE status = 'failed_review'"
            ).fetchone()[0]
            open_incidents = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'open'"
            ).fetchone()[0]
            critical_incidents = conn.execute(
                "SELECT COUNT(*) FROM incidents WHERE status = 'open' AND severity IN ('error', 'critical')"
            ).fetchone()[0]
            return {
                "query_count": query_count,
                "open_gap_count": gap_count,
                "failed_ingestion_count": failed_ingestions,
                "open_incident_count": open_incidents,
                "critical_incident_count": critical_incidents,
            }

    def _incident_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["context"] = json.loads(item.get("context") or "{}")
        except json.JSONDecodeError:
            item["context"] = {}
        return item
