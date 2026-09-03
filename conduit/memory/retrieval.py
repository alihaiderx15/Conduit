"""Prompt-friendly retrieval helpers for future agent integration."""

from __future__ import annotations

from .manager import MemoryManager


class MemoryRetriever:
    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    def context_for(self, query: str, *, limit: int = 5) -> str:
        results = self.manager.recall(query, limit=limit)
        if not results:
            return ""
        lines = ["Relevant local memories:"]
        for result in results:
            record = result.record
            lines.append(f"- [{record.category.value}] {record.key}: {record.value}")
        return "\n".join(lines)
