"""Repository layer for SQLite-backed Conduit memory."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from .database import MemoryDatabase
from .models import (
    Conversation,
    MemoryCategory,
    MemoryRecord,
    Message,
    ProjectFact,
    ProjectRecord,
    SearchResult,
    BehaviorRecord,
    DirectiveRecord,
    SessionRecap,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _text(value: datetime) -> str:
    return value.isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class MemoryRepository:
    """Perform persistence operations without applying product policy."""

    def __init__(self, database: MemoryDatabase) -> None:
        self.database = database
        self.connection = database.connection

    def create_conversation(self, title: str) -> Conversation:
        now = _now()
        cursor = self.connection.execute(
            "INSERT INTO conversations(title, created_at, updated_at) VALUES (?, ?, ?)",
            (title.strip(), _text(now), _text(now)),
        )
        self.connection.commit()
        return Conversation(int(cursor.lastrowid), title.strip(), now, now)

    def add_message(self, conversation_id: int, role: str, content: str) -> Message:
        now = _now()
        cursor = self.connection.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conversation_id, role.strip(), content, _text(now)),
        )
        self.connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (_text(now), conversation_id),
        )
        self.connection.commit()
        return Message(int(cursor.lastrowid), conversation_id, role.strip(), content, now)

    def get_messages(self, conversation_id: int) -> tuple[Message, ...]:
        rows = self.connection.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id",
            (conversation_id,),
        ).fetchall()
        return tuple(self._message(row) for row in rows)

    def upsert_memory(
        self,
        *,
        category: MemoryCategory,
        key: str,
        value: str,
        importance: float,
        source: str,
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        now = _now()
        self.connection.execute(
            """
            INSERT INTO memories(category, key, value, importance, source, metadata_json,
                                 created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(category, key) DO UPDATE SET
                value = excluded.value,
                importance = excluded.importance,
                source = excluded.source,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (
                category.value,
                key.strip(),
                value,
                importance,
                source,
                json.dumps(metadata or {}, ensure_ascii=False),
                _text(now),
                _text(now),
                _text(expires_at) if expires_at else None,
            ),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM memories WHERE category = ? AND key = ?",
            (category.value, key.strip()),
        ).fetchone()
        assert row is not None
        return self._memory(row)

    def get_memory(self, category: MemoryCategory, key: str) -> MemoryRecord | None:
        row = self.connection.execute(
            """
            SELECT * FROM memories
            WHERE category = ? AND key = ?
              AND (expires_at IS NULL OR expires_at > ?)
            """,
            (category.value, key.strip(), _text(_now())),
        ).fetchone()
        return self._memory(row) if row else None

    def list_memories(self, category: MemoryCategory | None = None) -> tuple[MemoryRecord, ...]:
        now = _text(_now())
        if category:
            rows = self.connection.execute(
                """SELECT * FROM memories WHERE category = ?
                   AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY importance DESC, updated_at DESC""",
                (category.value, now),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT * FROM memories WHERE expires_at IS NULL OR expires_at > ?
                   ORDER BY importance DESC, updated_at DESC""",
                (now,),
            ).fetchall()
        return tuple(self._memory(row) for row in rows)

    def search_memories(self, query: str, limit: int = 10) -> tuple[SearchResult, ...]:
        normalized = query.strip()
        if not normalized:
            return ()
        try:
            rows = self.connection.execute(
                """
                SELECT m.*, bm25(memory_fts) AS rank
                FROM memory_fts
                JOIN memories m ON m.id = memory_fts.rowid
                WHERE memory_fts MATCH ?
                  AND (m.expires_at IS NULL OR m.expires_at > ?)
                ORDER BY rank, m.importance DESC
                LIMIT ?
                """,
                (normalized, _text(_now()), limit),
            ).fetchall()
            return tuple(SearchResult(self._memory(row), float(-row["rank"])) for row in rows)
        except sqlite3.OperationalError:
            pattern = f"%{normalized}%"
            rows = self.connection.execute(
                """SELECT * FROM memories
                   WHERE (key LIKE ? OR value LIKE ?)
                     AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY importance DESC LIMIT ?""",
                (pattern, pattern, _text(_now()), limit),
            ).fetchall()
            return tuple(SearchResult(self._memory(row), row["importance"]) for row in rows)

    def touch_memory(self, memory_id: int) -> None:
        self.connection.execute(
            "UPDATE memories SET last_used_at = ? WHERE id = ?",
            (_text(_now()), memory_id),
        )
        self.connection.commit()

    def delete_memory(self, memory_id: int) -> bool:
        cursor = self.connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    def clear_memories(self, category: MemoryCategory | None = None) -> int:
        if category:
            cursor = self.connection.execute("DELETE FROM memories WHERE category = ?", (category.value,))
        else:
            cursor = self.connection.execute("DELETE FROM memories")
        self.connection.commit()
        return cursor.rowcount

    def purge_expired(self) -> int:
        cursor = self.connection.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
            (_text(_now()),),
        )
        self.connection.commit()
        return cursor.rowcount


    def increment_behavior(
        self,
        kind: str,
        value: str,
        *,
        amount: int = 1,
        score_delta: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> BehaviorRecord:
        now = _now()
        kind = str(kind or "").strip().casefold()
        value = str(value or "").strip()
        if not kind or not value:
            raise ValueError("Behavior kind and value are required.")
        self.connection.execute(
            """
            INSERT INTO behavior_stats(
                kind, value, count, score, metadata_json, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(kind, value) DO UPDATE SET
                count = behavior_stats.count + excluded.count,
                score = behavior_stats.score + excluded.score,
                metadata_json = excluded.metadata_json,
                last_seen_at = excluded.last_seen_at
            """,
            (
                kind, value, max(1, int(amount)), float(score_delta),
                json.dumps(metadata or {}, ensure_ascii=False),
                _text(now), _text(now),
            ),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM behavior_stats WHERE kind = ? AND value = ?",
            (kind, value),
        ).fetchone()
        assert row is not None
        return self._behavior(row)

    def top_behaviors(self, kind: str, *, limit: int = 10) -> tuple[BehaviorRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT * FROM behavior_stats
            WHERE kind = ?
            ORDER BY score DESC, count DESC, last_seen_at DESC
            LIMIT ?
            """,
            (str(kind or "").strip().casefold(), max(1, int(limit))),
        ).fetchall()
        return tuple(self._behavior(row) for row in rows)

    def upsert_directive(
        self,
        scope: str,
        key: str,
        value: str,
        *,
        source_text: str = "",
    ) -> DirectiveRecord:
        now = _now()
        scope = str(scope or "general").strip().casefold()
        key = str(key or "").strip().casefold()
        value = str(value or "").strip()
        if not key or not value:
            raise ValueError("Directive key and value are required.")
        self.connection.execute(
            """
            INSERT INTO directives(scope, key, value, source_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope, key) DO UPDATE SET
                value = excluded.value,
                source_text = excluded.source_text,
                updated_at = excluded.updated_at
            """,
            (scope, key, value, source_text, _text(now), _text(now)),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM directives WHERE scope = ? AND key = ?",
            (scope, key),
        ).fetchone()
        assert row is not None
        return self._directive(row)

    def list_directives(self, scope: str | None = None) -> tuple[DirectiveRecord, ...]:
        if scope:
            rows = self.connection.execute(
                "SELECT * FROM directives WHERE scope IN (?, 'general') ORDER BY updated_at DESC",
                (str(scope).casefold(),),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM directives ORDER BY updated_at DESC"
            ).fetchall()
        return tuple(self._directive(row) for row in rows)

    def add_session_recap(
        self,
        summary: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecap:
        now = _now()
        cursor = self.connection.execute(
            """
            INSERT INTO session_recaps(summary, metadata_json, created_at, consumed_at)
            VALUES (?, ?, ?, NULL)
            """,
            (str(summary).strip(), json.dumps(metadata or {}, ensure_ascii=False), _text(now)),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM session_recaps WHERE id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
        assert row is not None
        return self._recap(row)

    def latest_unconsumed_recap(self) -> SessionRecap | None:
        row = self.connection.execute(
            """
            SELECT * FROM session_recaps
            WHERE consumed_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
        return self._recap(row) if row else None

    def consume_recap(self, recap_id: int) -> bool:
        cursor = self.connection.execute(
            "UPDATE session_recaps SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
            (_text(_now()), int(recap_id)),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def upsert_project(self, name: str, description: str = "", path: str | None = None) -> ProjectRecord:
        now = _now()
        self.connection.execute(
            """
            INSERT INTO projects(name, description, path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                description = excluded.description,
                path = excluded.path,
                updated_at = excluded.updated_at
            """,
            (name.strip(), description, path, _text(now), _text(now)),
        )
        self.connection.commit()
        row = self.connection.execute("SELECT * FROM projects WHERE name = ?", (name.strip(),)).fetchone()
        assert row is not None
        return self._project(row)

    def set_project_fact(
        self,
        project_id: int,
        key: str,
        value: str,
        importance: float,
        source: str,
    ) -> ProjectFact:
        now = _now()
        self.connection.execute(
            """
            INSERT INTO project_facts(project_id, key, value, importance, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, key) DO UPDATE SET
                value = excluded.value,
                importance = excluded.importance,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (project_id, key.strip(), value, importance, source, _text(now), _text(now)),
        )
        self.connection.commit()
        row = self.connection.execute(
            "SELECT * FROM project_facts WHERE project_id = ? AND key = ?",
            (project_id, key.strip()),
        ).fetchone()
        assert row is not None
        return self._project_fact(row)


    def list_projects(self, *, limit: int = 10) -> tuple[ProjectRecord, ...]:
        rows = self.connection.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return tuple(self._project(row) for row in rows)

    def get_project_facts(self, project_id: int) -> tuple[ProjectFact, ...]:
        rows = self.connection.execute(
            "SELECT * FROM project_facts WHERE project_id = ? ORDER BY importance DESC, updated_at DESC",
            (project_id,),
        ).fetchall()
        return tuple(self._project_fact(row) for row in rows)

    @staticmethod
    def _message(row: sqlite3.Row) -> Message:
        return Message(row["id"], row["conversation_id"], row["role"], row["content"], _dt(row["created_at"]))  # type: ignore[arg-type]

    @staticmethod
    def _memory(row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            key=row["key"],
            value=row["value"],
            importance=float(row["importance"]),
            source=row["source"],
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_dt(row["updated_at"]),  # type: ignore[arg-type]
            last_used_at=_dt(row["last_used_at"]),
            expires_at=_dt(row["expires_at"]),
            metadata=json.loads(row["metadata_json"]),
        )


    @staticmethod
    def _behavior(row: sqlite3.Row) -> BehaviorRecord:
        return BehaviorRecord(
            id=int(row["id"]),
            kind=str(row["kind"]),
            value=str(row["value"]),
            count=int(row["count"]),
            score=float(row["score"]),
            first_seen_at=_dt(row["first_seen_at"]),  # type: ignore[arg-type]
            last_seen_at=_dt(row["last_seen_at"]),  # type: ignore[arg-type]
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _directive(row: sqlite3.Row) -> DirectiveRecord:
        return DirectiveRecord(
            id=int(row["id"]),
            scope=str(row["scope"]),
            key=str(row["key"]),
            value=str(row["value"]),
            source_text=str(row["source_text"]),
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
            updated_at=_dt(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _recap(row: sqlite3.Row) -> SessionRecap:
        return SessionRecap(
            id=int(row["id"]),
            summary=str(row["summary"]),
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
            consumed_at=_dt(row["consumed_at"]),
            metadata=json.loads(row["metadata_json"]),
        )

    @staticmethod
    def _project(row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            row["id"], row["name"], row["description"], row["path"],
            _dt(row["created_at"]), _dt(row["updated_at"]),  # type: ignore[arg-type]
        )

    @staticmethod
    def _project_fact(row: sqlite3.Row) -> ProjectFact:
        return ProjectFact(
            row["id"], row["project_id"], row["key"], row["value"],
            float(row["importance"]), row["source"],
            _dt(row["created_at"]), _dt(row["updated_at"]),  # type: ignore[arg-type]
        )
