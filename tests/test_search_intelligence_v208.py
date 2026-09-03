
from conduit.conversation.search_planner import _normalize_plan
from conduit.web_intelligence.models import SearchResult
from conduit.web_intelligence.service import WebIntelligenceService


def test_search_plan_preserves_query_variants_exclusions_preferences():
    raw = {
        "action": "web.research",
        "arguments": {
            "query": "banana health benefits studies",
            "depth": 2,
            "sources_per_query": 5,
            "use_grounding": False,
        },
        "intent": "research",
        "subject": "banana health benefits",
        "rewritten_request": "Research banana health benefits from studies",
        "query_variants": [
            "banana consumption health benefits clinical studies",
            "banana nutrition systematic review",
        ],
        "exclude_terms": ["dictionary definition"],
        "source_preferences": ["academic", "medical", "review"],
    }
    plan = _normalize_plan(raw, ["web.research"], "banana")
    assert len(plan.query_variants) == 2
    assert "dictionary definition" in plan.exclude_terms
    assert "academic" in plan.source_preferences
    assert plan.arguments["query_variants"] == list(plan.query_variants)


def test_exclusion_filter_removes_wrong_entity_meaning():
    results = [
        SearchResult(
            "Python programming language release",
            "https://python.org/news",
            "Developer and language update",
            "python.org",
        ),
        SearchResult(
            "Burmese python found in backyard",
            "https://news.example/snake",
            "Large snake discovered",
            "news.example",
        ),
    ]
    filtered = WebIntelligenceService._filter_exclusions(
        results,
        ["Burmese python", "snake"],
    )
    assert len(filtered) == 1
    assert "programming" in filtered[0].title.casefold()


def test_source_ranker_prefers_academic_sources():
    results = [
        SearchResult(
            "General health page",
            "https://example.com/health",
            "Generic page",
            "example.com",
        ),
        SearchResult(
            "Banana nutrition review",
            "https://pubmed.ncbi.nlm.nih.gov/123/",
            "Review of banana nutrition research",
            "pubmed.ncbi.nlm.nih.gov",
        ),
    ]
    ranked = WebIntelligenceService._rank_sources(
        results,
        ["academic", "medical", "review"],
    )
    assert "pubmed" in ranked[0].url
