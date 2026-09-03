
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import atexit
import json
import os
import re
import sqlite3
import tempfile
import time
from typing import Iterable, Iterator, Sequence


_TOKEN = re.compile(r"[A-Za-z0-9_]{3,}")


@dataclass(frozen=True, slots=True)
class SessionTurn:
    user: str
    assistant: str


@dataclass(frozen=True, slots=True)
class SessionEvent:
    name: str
    details: str


class SessionHistoryProxy(Sequence[SessionTurn]):
    """List-like compatibility layer backed by the temporary session database."""

    def __init__(self, store: "ShortTermSessionMemory") -> None:
        self.store = store

    def __len__(self) -> int:
        return self.store.turn_count()

    def __bool__(self) -> bool:
        return len(self) > 0

    def __iter__(self) -> Iterator[SessionTurn]:
        return iter(self.store.all_turns())

    def __eq__(self, other) -> bool:
        try:
            return self.store.all_turns() == list(other)
        except Exception:
            return False

    def __repr__(self) -> str:
        return repr(self.store.all_turns())

    def __getitem__(self, item):
        turns = self.store.all_turns()
        return turns[item]

    def append(self, turn) -> None:
        user = getattr(turn, "user", "")
        assistant = getattr(turn, "assistant", "")
        self.store.add(user, assistant)

    def extend(self, turns: Iterable) -> None:
        for turn in turns:
            self.append(turn)

    def clear(self) -> None:
        self.store.clear()


class ShortTermSessionMemory:
    """Temporary full-session transcript with bounded RAM usage.

    Exact turns/events live in a per-process SQLite file under the OS temp
    directory. The file is deleted by `clear()` / `close()` and atexit. Only
    recent turns/events are cached in RAM.

    This store is deliberately separate from Conduit's persistent user-memory DB.
    """

    def __init__(
        self,
        *,
        recent_cache_turns: int = 32,
        recent_cache_events: int = 80,
        temp_dir: str | Path | None = None,
    ) -> None:
        self.recent_cache_turns = max(4, int(recent_cache_turns))
        self.recent_cache_events = max(10, int(recent_cache_events))
        self.resume_context: str = ""
        self._closed = False

        base = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())/"Conduit"/"sessions"
        base.mkdir(parents=True, exist_ok=True)
        self._cleanup_stale(base)

        stamp = f"{os.getpid()}-{time.time_ns()}"
        self.path = base/f"session-{stamp}.sqlite3"
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;

            CREATE TABLE turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL,
                assistant TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at REAL NOT NULL
            );

            CREATE INDEX idx_turns_created ON turns(created_at);
            CREATE INDEX idx_events_created ON events(created_at);
            """
        )
        self.connection.commit()

        self._recent_turns: list[SessionTurn] = []
        self._recent_events: list[SessionEvent] = []
        self.history = SessionHistoryProxy(self)
        atexit.register(self.close)

    @staticmethod
    def _cleanup_stale(base: Path) -> None:
        """Remove abandoned raw-session files from previous crashed processes."""
        cutoff = time.time() - (24 * 60 * 60)
        try:
            for path in base.glob("session-*.sqlite3*"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass

    @property
    def turns(self) -> list[SessionTurn]:
        """Compatibility snapshot; exact transcript remains disk-backed."""
        return self.all_turns()

    @property
    def events(self) -> list[SessionEvent]:
        """Compatibility snapshot of stored events."""
        if self._closed:
            return []
        rows = self.connection.execute(
            "SELECT name, details FROM events ORDER BY id"
        ).fetchall()
        return [SessionEvent(str(r["name"]), str(r["details"])) for r in rows]

    def add(self, user: str, assistant: str) -> None:
        if self._closed:
            return
        turn = SessionTurn(str(user), str(assistant))
        self.connection.execute(
            "INSERT INTO turns(user, assistant, created_at) VALUES (?, ?, ?)",
            (turn.user, turn.assistant, time.time()),
        )
        self.connection.commit()
        self._recent_turns.append(turn)
        if len(self._recent_turns) > self.recent_cache_turns:
            del self._recent_turns[:-self.recent_cache_turns]

    def add_event(self, name: str, details: str) -> None:
        if self._closed:
            return
        event = SessionEvent(str(name), str(details))
        self.connection.execute(
            "INSERT INTO events(name, details, created_at) VALUES (?, ?, ?)",
            (event.name, event.details, time.time()),
        )
        self.connection.commit()
        self._recent_events.append(event)
        if len(self._recent_events) > self.recent_cache_events:
            del self._recent_events[:-self.recent_cache_events]

    def turn_count(self) -> int:
        if self._closed:
            return 0
        row = self.connection.execute("SELECT COUNT(*) AS n FROM turns").fetchone()
        return int(row["n"] if row else 0)

    def event_count(self) -> int:
        if self._closed:
            return 0
        row = self.connection.execute("SELECT COUNT(*) AS n FROM events").fetchone()
        return int(row["n"] if row else 0)

    def __len__(self) -> int:
        return self.turn_count()

    def all_turns(self) -> list[SessionTurn]:
        if self._closed:
            return []
        rows = self.connection.execute(
            "SELECT user, assistant FROM turns ORDER BY id"
        ).fetchall()
        return [SessionTurn(str(r["user"]), str(r["assistant"])) for r in rows]

    def recent_turns(self, limit: int = 12) -> list[SessionTurn]:
        limit = max(1, int(limit))
        if limit <= len(self._recent_turns):
            return list(self._recent_turns[-limit:])
        if self._closed:
            return []
        rows = self.connection.execute(
            "SELECT user, assistant FROM turns ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows = list(reversed(rows))
        return [SessionTurn(str(r["user"]), str(r["assistant"])) for r in rows]

    def turn_at(self, index: int) -> SessionTurn | None:
        """Return zero-based positive/negative indexed turn without loading all."""
        count = self.turn_count()
        if count == 0:
            return None
        idx = int(index)
        if idx < 0:
            idx = count + idx
        if idx < 0 or idx >= count:
            return None
        row = self.connection.execute(
            "SELECT user, assistant FROM turns ORDER BY id LIMIT 1 OFFSET ?",
            (idx,),
        ).fetchone()
        return SessionTurn(str(row["user"]), str(row["assistant"])) if row else None

    def search_turns(self, query: str, *, limit: int = 8, exclude_recent: int = 12) -> list[SessionTurn]:
        if self._closed or not query.strip():
            return []
        query_tokens = self._tokens(query)
        if not query_tokens:
            return []

        # Scan stored text one row at a time. The raw transcript is on disk; only
        # the highest scoring small set is retained in RAM during retrieval.
        count = self.turn_count()
        older_count = max(0, count - max(0, int(exclude_recent)))
        if older_count <= 0:
            return []

        cursor = self.connection.execute(
            "SELECT user, assistant FROM turns ORDER BY id LIMIT ?",
            (older_count,),
        )
        scored: list[tuple[int, SessionTurn]] = []
        query_lower = query.casefold().strip()
        for row in cursor:
            turn = SessionTurn(str(row["user"]), str(row["assistant"]))
            combined = turn.user + " " + turn.assistant
            overlap = len(self._tokens(combined) & query_tokens)
            exact_bonus = 100 if query_lower and query_lower in combined.casefold() else 0
            score = overlap + exact_bonus
            if score:
                scored.append((score, turn))
                scored.sort(key=lambda x: x[0], reverse=True)
                if len(scored) > max(1, int(limit)):
                    scored.pop()
        return [turn for _, turn in scored]

    def recent_events(self, limit: int = 10) -> list[SessionEvent]:
        limit = max(1, int(limit))
        if limit <= len(self._recent_events):
            return list(self._recent_events[-limit:])
        if self._closed:
            return []
        rows = self.connection.execute(
            "SELECT name, details FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows = list(reversed(rows))
        return [SessionEvent(str(r["name"]), str(r["details"])) for r in rows]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {x.casefold() for x in _TOKEN.findall(text)}

    def context_for(
        self,
        query: str,
        *,
        recent_turns: int = 12,
        relevant_older: int = 8,
        max_chars: int = 18000,
    ) -> str:
        recent = self.recent_turns(recent_turns)
        older = self.search_turns(
            query,
            limit=relevant_older,
            exclude_recent=recent_turns,
        )

        if not recent and not older and not self.resume_context:
            return ""

        lines: list[str] = []
        if self.resume_context:
            lines += ["Previous-session recap:", self.resume_context]

        seen = set()
        for turn in [*older, *recent]:
            key = (turn.user, turn.assistant)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"User: {turn.user}")
            lines.append(f"Conduit: {turn.assistant}")

        query_tokens = self._tokens(query)
        relevant_events = []
        for event in self.recent_events(30):
            combined = f"{event.name} {event.details}"
            if not query_tokens or self._tokens(combined) & query_tokens:
                relevant_events.append(event)
        if relevant_events:
            lines.append("Recent Conduit execution trace:")
            for event in relevant_events[-10:]:
                details = event.details.replace("\n", " ")[:500]
                lines.append(f"- {event.name}: {details}")

        text = "\n".join(lines)
        return text[-max_chars:] if len(text) > max_chars else text

    def deterministic_recap(self, *, max_chars: int = 2200) -> str:
        turns = self.recent_turns(10)
        if not turns:
            return ""
        lines = []
        for turn in turns:
            user = " ".join(turn.user.split())
            answer = " ".join(turn.assistant.split())
            if len(user) > 180:
                user = user[:177] + "..."
            if len(answer) > 280:
                answer = answer[:277] + "..."
            lines.append(f"- User: {user}")
            lines.append(f"  Conduit: {answer}")
        return "\n".join(lines)[:max_chars]

    def clear(self) -> None:
        """Wipe the exact session transcript while keeping the store reusable."""
        if self._closed:
            return
        self.connection.execute("DELETE FROM turns")
        self.connection.execute("DELETE FROM events")
        self.connection.commit()
        self._recent_turns.clear()
        self._recent_events.clear()
        self.resume_context = ""

    def close(self) -> None:
        """Close and securely-ish remove this temporary raw-session database."""
        if self._closed:
            return
        self._closed = True
        try:
            self.connection.close()
        except Exception:
            pass

        # SQLite WAL/SHM companions may exist.
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(str(self.path) + suffix).unlink(missing_ok=True)
            except OSError:
                pass
