"""Structured web search, news, research, pricing, and comparison."""
from .models import SearchResult, SearchResponse
from .service import WebIntelligenceService, UnsafeSearchQueryError

__all__ = [
    "SearchResult",
    "SearchResponse",
    "WebIntelligenceService",
    "UnsafeSearchQueryError",
]
