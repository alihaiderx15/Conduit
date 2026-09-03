"""High-level memory manager with policy checks and event emission."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from conduit.events.bus import EventBus
from conduit.events.names import EventNames

from .database import MemoryDatabase
from .models import MemoryCategory, MemoryRecord, ProjectFact, ProjectRecord, SearchResult
from .policies import MemoryPolicy
from .repository import MemoryRepository


class MemoryManager:
    """Privacy-first facade for Conduit's local persistent memory."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        policy: MemoryPolicy | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.database = MemoryDatabase(database_path)
        self.repository = MemoryRepository(self.database)
        self.policy = policy or MemoryPolicy()
        self.event_bus = event_bus

    def remember(
        self,
        key: str,
        value: str,
        *,
        category: MemoryCategory = MemoryCategory.FACT,
        importance: float = 0.5,
        source: str = "user",
        metadata: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryRecord:
        self.policy.validate(key, value)
        if not 0 <= importance <= 1:
            raise ValueError("Memory importance must be between 0 and 1.")
        record = self.repository.upsert_memory(
            category=category,
            key=key,
            value=value,
            importance=importance,
            source=source,
            metadata=metadata,
            expires_at=expires_at,
        )
        self._emit(EventNames.MEMORY_SAVED, {"id": record.id, "category": record.category.value, "key": record.key})
        return record

    def recall(self, query: str, *, limit: int = 10) -> tuple[SearchResult, ...]:
        results = self.repository.search_memories(query, limit=limit)
        for result in results:
            self.repository.touch_memory(result.record.id)
        self._emit(EventNames.MEMORY_RECALLED, {"query": query, "results": len(results)})
        return results

    def forget(self, memory_id: int) -> bool:
        deleted = self.repository.delete_memory(memory_id)
        if deleted:
            self._emit(EventNames.MEMORY_DELETED, {"id": memory_id})
        return deleted


    def directives(self, scope: str | None = None):
        return self.repository.list_directives(scope)

    def directive(self, scope: str, key: str) -> str:
        wanted_scope = str(scope or "general").casefold()
        wanted_key = str(key or "").casefold()
        for row in self.repository.list_directives(wanted_scope):
            if row.key == wanted_key and row.scope in {wanted_scope, "general"}:
                return row.value
        return ""

    def top_behaviors(self, kind: str, *, limit: int = 5):
        return self.repository.top_behaviors(kind, limit=limit)

    def create_project(self, name: str, *, description: str = "", path: str | None = None) -> ProjectRecord:
        return self.repository.upsert_project(name, description, path)

    def remember_project_fact(
        self,
        project_id: int,
        key: str,
        value: str,
        *,
        importance: float = 0.5,
        source: str = "user",
    ) -> ProjectFact:
        self.policy.validate(key, value)
        return self.repository.set_project_fact(project_id, key, value, importance, source)

    def close(self) -> None:
        self.database.close()

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.event_bus:
            self.event_bus.emit_nowait(name, source="MemoryManager", payload=payload)

    def __enter__(self) -> "MemoryManager":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
