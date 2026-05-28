from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import VALID_FEEDBACK
from .utils import utc_now
from .text_cleaning import normalized_text

VALID_INCIDENT_SEVERITIES = {"info", "warning", "error", "critical"}
VALID_INCIDENT_STATUSES = {"open", "resolved", "ignored"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        result = super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return bool(result)


class QualityDatabase:
    def __init__(self, root: Path):
        self.path = root / "data" / "poc_quality.db"

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, factory=ClosingConnection)
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
                    session_id TEXT,
                    template_id TEXT,
                    policy_id TEXT,
                    policy_version TEXT,
                    retrieved_doc_ids TEXT NOT NULL,
                    answer_has_citation INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    feedback TEXT,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "query_logs", "session_id", "TEXT")
            self._ensure_column(conn, "query_logs", "template_id", "TEXT")
            self._ensure_column(conn, "query_logs", "policy_id", "TEXT")
            self._ensure_column(conn, "query_logs", "policy_version", "TEXT")
            self._ensure_column(conn, "query_logs", "llm_used", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "query_logs", "llm_error", "TEXT")
            self._ensure_column(conn, "query_logs", "answer_source", "TEXT")
            self._ensure_column(conn, "query_logs", "llm_provider", "TEXT")
            self._ensure_column(conn, "query_logs", "llm_model", "TEXT")
            self._ensure_column(conn, "query_logs", "tokens_prompt", "INTEGER DEFAULT 0")
            self._ensure_column(conn, "query_logs", "tokens_completion", "INTEGER DEFAULT 0")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_annotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    query_normalized TEXT NOT NULL UNIQUE,
                    annotated_answer TEXT NOT NULL,
                    doc_id TEXT,
                    version TEXT,
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    device_id TEXT,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
                """
            )
            self._ensure_column(conn, "user_chat_sessions", "context_json", "TEXT")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_chat_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    effective_query TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    citation_doc_ids TEXT NOT NULL,
                    query_log_id INTEGER,
                    template_id TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_chat_turns_session_created
                ON user_chat_turns (session_id, created_at)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_user_chat_sessions_expires_at
                ON user_chat_sessions (expires_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS answer_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    answer_run_id TEXT NOT NULL UNIQUE,
                    query_log_id INTEGER,
                    session_id TEXT,
                    user_question TEXT NOT NULL,
                    intent TEXT,
                    stage TEXT NOT NULL,
                    retrieval_round INTEGER NOT NULL,
                    revision_round INTEGER NOT NULL,
                    answer_quality_status TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    final_confidence REAL NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_answer_runs_session_created
                ON answer_runs (session_id, created_at)
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
        *,
        llm_used: bool = False,
        llm_error: str | None = None,
        answer_source: str | None = None,
        llm_provider: str | None = None,
        llm_model: str | None = None,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
    ) -> int:
        self.init()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO query_logs (
                    query, user_id, retrieved_doc_ids, answer_has_citation, latency_ms, answer, created_at,
                    llm_used, llm_error, answer_source, llm_provider, llm_model, tokens_prompt, tokens_completion
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query,
                    user_id,
                    json.dumps(retrieved_doc_ids, ensure_ascii=False),
                    1 if answer_has_citation else 0,
                    latency_ms,
                    answer,
                    utc_now(),
                    1 if llm_used else 0,
                    llm_error,
                    answer_source,
                    llm_provider,
                    llm_model,
                    tokens_prompt,
                    tokens_completion,
                ),
            )
            return int(cursor.lastrowid)

    def annotate_query(
        self,
        log_id: int,
        *,
        session_id: str | None = None,
        template_id: str | None = None,
        policy_id: str | None = None,
        policy_version: str | None = None,
    ) -> dict[str, Any]:
        self.init()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM query_logs WHERE id = ?", (log_id,)).fetchone()
            if not row:
                raise ValueError(f"Query log not found: {log_id}")
            conn.execute(
                """
                UPDATE query_logs
                SET session_id = ?, template_id = ?, policy_id = ?, policy_version = ?
                WHERE id = ?
                """,
                (session_id, template_id, policy_id, policy_version, log_id),
            )
            updated = conn.execute("SELECT * FROM query_logs WHERE id = ?", (log_id,)).fetchone()
            return dict(updated)

    def get_annotation(self, query: str) -> dict[str, Any] | None:
        self.init()
        norm = normalized_text(query).strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM rag_annotations WHERE query_normalized = ?",
                (norm,),
            ).fetchone()
            if row:
                return dict(row)
        return None

    def add_or_update_annotation(
        self,
        query: str,
        annotated_answer: str,
        doc_id: str | None = None,
        version: str | None = None,
    ) -> int:
        self.init()
        norm = normalized_text(query).strip()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id FROM rag_annotations WHERE query_normalized = ?",
                (norm,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE rag_annotations
                    SET query = ?, annotated_answer = ?, doc_id = ?, version = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (query, annotated_answer, doc_id, version, utc_now(), row["id"]),
                )
                return int(row["id"])
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO rag_annotations (query, query_normalized, annotated_answer, doc_id, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (query, norm, annotated_answer, doc_id, version, utc_now()),
                )
                return int(cursor.lastrowid)

    def list_annotations(self) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM rag_annotations ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def delete_annotation(self, annotation_id: int) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute("DELETE FROM rag_annotations WHERE id = ?", (annotation_id,))

    def delete_gaps(self, gap_ids: list[int]) -> None:
        self.init()
        if not gap_ids:
            return
        placeholders = ",".join("?" for _ in gap_ids)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM knowledge_gaps WHERE id IN ({placeholders})", gap_ids)

    def delete_queries(self, query_ids: list[int]) -> None:
        self.init()
        if not query_ids:
            return
        placeholders = ",".join("?" for _ in query_ids)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM query_logs WHERE id IN ({placeholders})", query_ids)

    def delete_ingestion_runs(self, run_ids: list[int]) -> None:
        self.init()
        if not run_ids:
            return
        placeholders = ",".join("?" for _ in run_ids)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM ingestion_runs WHERE id IN ({placeholders})", run_ids)

    def delete_incidents(self, incident_ids: list[int]) -> None:
        self.init()
        if not incident_ids:
            return
        placeholders = ",".join("?" for _ in incident_ids)
        with self.connect() as conn:
            conn.execute(f"DELETE FROM incidents WHERE id IN ({placeholders})", incident_ids)

    def bulk_update_gaps_status(self, gap_ids: list[int], status: str) -> None:
        self.init()
        if not gap_ids:
            return
        placeholders = ",".join("?" for _ in gap_ids)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE knowledge_gaps SET status = ? WHERE id IN ({placeholders})",
                [status] + gap_ids,
            )

    def bulk_update_queries_feedback(self, query_ids: list[int], feedback: str) -> None:
        self.init()
        if not query_ids:
            return
        placeholders = ",".join("?" for _ in query_ids)
        with self.connect() as conn:
            conn.execute(
                f"UPDATE query_logs SET feedback = ? WHERE id IN ({placeholders})",
                [feedback] + query_ids,
            )

    def bulk_resolve_incidents(self, incident_ids: list[int], status: str) -> None:
        self.init()
        if not incident_ids:
            return
        placeholders = ",".join("?" for _ in incident_ids)
        now_text = utc_now() if status in {"resolved", "ignored"} else None
        with self.connect() as conn:
            conn.execute(
                f"UPDATE incidents SET status = ?, resolved_at = ? WHERE id IN ({placeholders})",
                [status, now_text] + incident_ids,
            )

    def touch_user_chat_session(
        self,
        session_id: str,
        *,
        device_id: str | None = None,
        ttl_seconds: int = 1800,
    ) -> dict[str, Any]:
        self.init()
        now = _utc_now_dt()
        now_text = _iso(now)
        expires_at = _iso(now + timedelta(seconds=max(1, int(ttl_seconds))))
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE user_chat_sessions
                    SET device_id = COALESCE(?, device_id), last_seen_at = ?, expires_at = ?
                    WHERE session_id = ?
                    """,
                    (device_id, now_text, expires_at, session_id),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO user_chat_sessions (session_id, device_id, created_at, last_seen_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, device_id, now_text, now_text, expires_at),
                )
            updated = conn.execute(
                "SELECT * FROM user_chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(updated)

    def user_chat_context(self, session_id: str) -> dict[str, Any]:
        self.init()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT context_json FROM user_chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row or not row["context_json"]:
            return {}
        try:
            parsed = json.loads(str(row["context_json"]))
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def update_user_chat_context(self, session_id: str, context: dict[str, Any]) -> None:
        self.init()
        with self.connect() as conn:
            conn.execute(
                "UPDATE user_chat_sessions SET context_json = ? WHERE session_id = ?",
                (json.dumps(context, ensure_ascii=False), session_id),
            )

    def log_user_chat_turn(
        self,
        session_id: str,
        *,
        query: str,
        effective_query: str,
        answer: str,
        citation_doc_ids: list[str],
        query_log_id: int | None = None,
        template_id: str | None = None,
    ) -> int:
        self.init()
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO user_chat_turns (
                    session_id, query, effective_query, answer, citation_doc_ids, query_log_id, template_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    query,
                    effective_query,
                    answer,
                    json.dumps(citation_doc_ids, ensure_ascii=False),
                    query_log_id,
                    template_id,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def log_answer_run(
        self,
        answer_run: dict[str, Any],
        *,
        query_log_id: int | None = None,
        session_id: str | None = None,
        user_question: str | None = None,
    ) -> int:
        self.init()
        answer_run_id = str(answer_run.get("answer_run_id") or uuid.uuid4())
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO answer_runs (
                    answer_run_id, query_log_id, session_id, user_question, intent, stage,
                    retrieval_round, revision_round, answer_quality_status, evidence_status,
                    final_confidence, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    answer_run_id,
                    query_log_id,
                    session_id,
                    user_question or str(answer_run.get("user_question") or ""),
                    str(answer_run.get("intent") or ""),
                    str(answer_run.get("stage") or "failed"),
                    int(answer_run.get("retrieval_round") or 0),
                    int(answer_run.get("revision_round") or 0),
                    str(answer_run.get("answer_quality_status") or "failed"),
                    str(answer_run.get("evidence_status") or "unknown"),
                    float(answer_run.get("final_confidence") or 0.0),
                    json.dumps(answer_run, ensure_ascii=False),
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def recent_user_chat_turns(self, session_id: str, limit: int = 6) -> list[dict[str, Any]]:
        self.init()
        limit = max(1, min(int(limit), 20))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_chat_turns
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
            return [self._user_chat_turn_row(row) for row in reversed(rows)]

    def get_user_chat_session(self, session_id: str) -> dict[str, Any] | None:
        self.init()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM user_chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_user_chat_session(self, session_id: str) -> int:
        self.init()
        with self.connect() as conn:
            turn_count = conn.execute(
                "SELECT COUNT(*) FROM user_chat_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()[0]
            conn.execute("DELETE FROM user_chat_turns WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM user_chat_sessions WHERE session_id = ?", (session_id,))
            return int(turn_count)

    def cleanup_stale_user_chat_sessions(self, now: str | None = None) -> dict[str, Any]:
        self.init()
        current = now or utc_now()
        with self.connect() as conn:
            session_ids = [
                str(row["session_id"])
                for row in conn.execute(
                    "SELECT session_id FROM user_chat_sessions WHERE expires_at <= ?",
                    (current,),
                ).fetchall()
            ]
            turn_count = 0
            for session_id in session_ids:
                turn_count += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM user_chat_turns WHERE session_id = ?",
                        (session_id,),
                    ).fetchone()[0]
                )
                conn.execute("DELETE FROM user_chat_turns WHERE session_id = ?", (session_id,))
                conn.execute("DELETE FROM user_chat_sessions WHERE session_id = ?", (session_id,))
            return {
                "deleted_sessions": len(session_ids),
                "deleted_turns": turn_count,
                "session_ids": session_ids,
            }

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

    def get_incident(self, incident_id: int) -> dict[str, Any] | None:
        self.init()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            return self._incident_row(row) if row else None

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

    def list_user_sessions_by_device(self, device_id: str) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.*,
                       (SELECT t.query FROM user_chat_turns t WHERE t.session_id = s.session_id ORDER BY t.id ASC LIMIT 1) as title
                FROM user_chat_sessions s
                WHERE s.device_id = ?
                ORDER BY s.last_seen_at DESC
                """,
                (device_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_user_chat_turns(self, session_id: str) -> list[dict[str, Any]]:
        self.init()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM user_chat_turns
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
            return [self._user_chat_turn_row(row) for row in rows]

    def _incident_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["context"] = json.loads(item.get("context") or "{}")
        except json.JSONDecodeError:
            item["context"] = {}
        return item

    def _user_chat_turn_row(self, row: sqlite3.Row) -> dict[str, Any]:
        item = dict(row)
        try:
            item["citation_doc_ids"] = json.loads(item.get("citation_doc_ids") or "[]")
        except json.JSONDecodeError:
            item["citation_doc_ids"] = []
        return item

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _utc_now_dt() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
