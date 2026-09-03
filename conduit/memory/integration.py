"""Bridge persistent local memory into Conduit's dynamic agent."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable

from conduit.events.bus import EventBus
from conduit.events.names import EventNames

from .manager import MemoryManager
from .models import MemoryCategory, MemoryRecord
from .policies import SensitiveMemoryError

_TOKEN = re.compile(r"[A-Za-z0-9_]{3,}")
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "you", "use",
    "open", "please", "should", "would", "could", "what", "when", "where", "which", "about",
}


class MemoryWriteMode(StrEnum):
    """How model-proposed long-term memories are handled."""

    NEVER = "never"
    PROPOSE_ONLY = "propose_only"
    AUTO_SAFE = "auto_safe"


@dataclass(frozen=True, slots=True)
class MemoryProposal:
    """A model-proposed fact that may be worth retaining beyond the current task."""

    key: str
    value: str
    category: MemoryCategory = MemoryCategory.FACT
    importance: float = 0.5
    reason: str = ""


@dataclass(frozen=True, slots=True)
class MemoryInjection:
    """Relevant memories selected for one agent run."""

    query: str
    records: tuple[MemoryRecord, ...] = ()
    prompt_text: str = ""


@dataclass(frozen=True, slots=True)
class MemoryProposalResult:
    proposal: MemoryProposal
    saved: bool
    record: MemoryRecord | None = None
    reason: str = ""


class AgentMemoryBridge:
    """Retrieve relevant memories and safely handle model memory proposals."""

    def __init__(
        self,
        manager: MemoryManager,
        *,
        write_mode: MemoryWriteMode = MemoryWriteMode.PROPOSE_ONLY,
        event_bus: EventBus | None = None,
        retrieval_limit: int = 6,
    ) -> None:
        self.manager = manager
        self.write_mode = write_mode
        self.events = event_bus
        self.retrieval_limit = max(1, retrieval_limit)

    def retrieve(self, query: str) -> MemoryInjection:
        """Select useful local memories for the current goal."""
        search_query = self._fts_query(query)
        results = self.manager.recall(search_query, limit=self.retrieval_limit) if search_query else ()
        records = tuple(item.record for item in results)

        # FTS can miss wording variants. Fill remaining slots with high-importance
        # memories whose words overlap the goal, then with important preferences.
        existing = {record.id for record in records}
        query_tokens = set(self._tokens(query))
        candidates = []
        for record in self.manager.repository.list_memories():
            if record.id in existing:
                continue
            record_tokens = set(self._tokens(f"{record.key} {record.value}"))
            overlap = len(query_tokens & record_tokens)
            preference_bonus = 1 if record.category is MemoryCategory.PREFERENCE else 0
            if overlap or preference_bonus:
                candidates.append((overlap, preference_bonus, record.importance, record))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        records += tuple(item[3] for item in candidates[: max(0, self.retrieval_limit - len(records))])

        lines = []
        if records:
            lines.append("Relevant persistent user memories (context only; obey explicit user directives when applicable):")
            for record in records:
                lines.append(f"- [{record.category.value}] {record.key}: {record.value}")

        lowered = query.casefold()
        if any(x in lowered for x in ("code", "python", "cpp", "project", "developer")):
            scope = "code"
        elif any(x in lowered for x in ("youtube", "video", "channel")):
            scope = "youtube"
        elif any(x in lowered for x in ("browser", "chrome", "opera", "firefox", "edge", "tab")):
            scope = "browser"
        elif any(x in lowered for x in ("game", "steam", "epic")):
            scope = "games"
        elif any(x in lowered for x in ("file", "pdf", "docx", "excel", "image")):
            scope = "files"
        else:
            scope = "general"

        directives = self.manager.repository.list_directives(scope)
        if directives:
            lines.append("Applicable user directives:")
            for directive in directives[:8]:
                lines.append(f"- [{directive.scope}] {directive.key}: {directive.value}")
        injection = MemoryInjection(query=query, records=records, prompt_text="\n".join(lines))
        self._emit(EventNames.MEMORY_INJECTED, {"query": query, "count": len(records)})
        return injection

    def handle_proposals(self, proposals: Iterable[MemoryProposal]) -> tuple[MemoryProposalResult, ...]:
        """Apply the configured write policy to proposed memories."""
        results: list[MemoryProposalResult] = []
        for proposal in proposals:
            if self.write_mode is MemoryWriteMode.NEVER:
                result = MemoryProposalResult(proposal, False, reason="Memory writing is disabled.")
            elif self.write_mode is MemoryWriteMode.PROPOSE_ONLY:
                result = MemoryProposalResult(proposal, False, reason="Awaiting user approval.")
                self._emit(
                    EventNames.MEMORY_PROPOSED,
                    {"key": proposal.key, "category": proposal.category.value, "reason": proposal.reason},
                )
            else:
                try:
                    record = self.manager.remember(
                        proposal.key,
                        proposal.value,
                        category=proposal.category,
                        importance=proposal.importance,
                        source="agent",
                        metadata={"reason": proposal.reason},
                    )
                    result = MemoryProposalResult(proposal, True, record=record, reason="Saved by safe auto-memory policy.")
                except (SensitiveMemoryError, ValueError) as exc:
                    result = MemoryProposalResult(proposal, False, reason=str(exc))
                    self._emit(
                        EventNames.MEMORY_REJECTED,
                        {"key": proposal.key, "category": proposal.category.value, "reason": str(exc)},
                    )
            results.append(result)
        return tuple(results)

    @classmethod
    def _tokens(cls, text: str) -> tuple[str, ...]:
        return tuple(
            token.lower() for token in _TOKEN.findall(text)
            if token.lower() not in _STOPWORDS
        )

    @classmethod
    def _fts_query(cls, text: str) -> str:
        tokens = cls._tokens(text)
        # OR gives memory retrieval recall; every token is quoted to avoid FTS operators.
        return " OR ".join(f'"{token}"' for token in tokens[:12])

    def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self.events:
            self.events.emit_nowait(name, source="AgentMemoryBridge", payload=payload)
