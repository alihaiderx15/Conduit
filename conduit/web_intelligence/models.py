"""Data models for Conduit's Web Intelligence Pack."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = ""
    published_at: str | None = None
    price: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    mode: str
    provider: str
    results: tuple[SearchResult, ...] = ()
    answer: str = ""
    sources: tuple[SearchResult, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "provider": self.provider,
            "answer": self.answer,
            "results": [item.to_dict() for item in self.results],
            "sources": [item.to_dict() for item in self.sources],
            "metadata": dict(self.metadata),
        }
