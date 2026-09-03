"""SQLite database and schema migrations for Conduit memory."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


class MemoryDatabase:
    """Own a local SQLite connection and apply forward-only migrations."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        current = int(self.connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Memory database schema {current} is newer than supported schema {SCHEMA_VERSION}."
            )
        if current < 1:
            self.connection.executescript(
                """
                CREATE TABLE conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);

                CREATE TABLE memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5 CHECK(importance >= 0 AND importance <= 1),
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    expires_at TEXT,
                    UNIQUE(category, key)
                );
                CREATE INDEX idx_memories_category ON memories(category);
                CREATE INDEX idx_memories_expiry ON memories(expires_at);

                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL DEFAULT '',
                    path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE project_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance REAL NOT NULL DEFAULT 0.5 CHECK(importance >= 0 AND importance <= 1),
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(project_id, key)
                );
                CREATE INDEX idx_project_facts_project ON project_facts(project_id);

                CREATE VIRTUAL TABLE memory_fts USING fts5(
                    key,
                    value,
                    content='memories',
                    content_rowid='id'
                );

                CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memory_fts(rowid, key, value) VALUES (new.id, new.key, new.value);
                END;
                CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, key, value)
                    VALUES ('delete', old.id, old.key, old.value);
                END;
                CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memory_fts(memory_fts, rowid, key, value)
                    VALUES ('delete', old.id, old.key, old.value);
                    INSERT INTO memory_fts(rowid, key, value) VALUES (new.id, new.key, new.value);
                END;
                """
            )
            self.connection.execute("PRAGMA user_version = 1")
            self.connection.commit()
            current = 1

        if current < 2:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS behavior_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    value TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 1,
                    score REAL NOT NULL DEFAULT 1.0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(kind, value)
                );
                CREATE INDEX IF NOT EXISTS idx_behavior_kind_count
                    ON behavior_stats(kind, count DESC, score DESC);

                CREATE TABLE IF NOT EXISTS directives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope, key)
                );
                CREATE INDEX IF NOT EXISTS idx_directives_scope ON directives(scope);

                CREATE TABLE IF NOT EXISTS session_recaps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_session_recaps_consumed
                    ON session_recaps(consumed_at, created_at DESC);
                """
            )
            self.connection.execute("PRAGMA user_version = 2")
            self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "MemoryDatabase":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
