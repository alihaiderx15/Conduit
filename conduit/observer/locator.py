"""Element lookup helpers for structured screen analyses."""
from __future__ import annotations

from difflib import SequenceMatcher

from conduit.observer.models import ScreenElement, StructuredScreenAnalysis


class ScreenElementNotFound(LookupError):
    pass


class ScreenLocator:
    """Search visible elements by label, text, role, or stable id."""

    def __init__(self, analysis: StructuredScreenAnalysis) -> None:
        self.analysis = analysis

    @staticmethod
    def _score(query: str, element: ScreenElement) -> float:
        query = query.casefold().strip()
        candidates = [element.element_id, element.label, element.text, element.role]
        scores = []
        for candidate in candidates:
            normalized = candidate.casefold().strip()
            if not normalized:
                continue
            if query == normalized:
                scores.append(1.0)
            elif query in normalized or normalized in query:
                scores.append(0.92)
            else:
                scores.append(SequenceMatcher(None, query, normalized).ratio())
        return max(scores, default=0.0) * max(0.25, element.confidence)

    def find_all(self, query: str, *, role: str | None = None, minimum_score: float = 0.42) -> tuple[ScreenElement, ...]:
        matches: list[tuple[float, ScreenElement]] = []
        for element in self.analysis.elements:
            if not element.visible:
                continue
            if role and element.role.casefold() != role.casefold():
                continue
            score = self._score(query, element)
            if score >= minimum_score:
                matches.append((score, element))
        matches.sort(key=lambda item: item[0], reverse=True)
        return tuple(element for _, element in matches)

    def find(self, query: str, *, role: str | None = None) -> ScreenElement:
        matches = self.find_all(query, role=role)
        if not matches:
            raise ScreenElementNotFound(f"No visible screen element matched '{query}'.")
        return matches[0]

    def exists(self, query: str, *, role: str | None = None) -> bool:
        return bool(self.find_all(query, role=role))
