
from conduit.web_intelligence.models import SearchResult
from conduit.web_intelligence.service import WebIntelligenceService
from conduit.conversation.session import ConversationSession


def test_adult_results_are_hard_filtered():
    bad = SearchResult(
        "Adult video site",
        "https://example-porn.invalid/videos",
        "porn xxx videos",
        "example",
    )
    good = SearchResult(
        "Most runs in international cricket",
        "https://example.com/cricket-records",
        "International cricket batting records and run totals",
        "example.com",
    )
    safe = WebIntelligenceService._safe_results([bad, good])
    assert safe == [good]


def test_cricket_query_rejects_unrelated_safe_result_when_topical_exists():
    irrelevant = SearchResult(
        "Best gardening equipment",
        "https://example.com/garden",
        "Tools for outdoor gardening",
        "example.com",
    )
    cricket = SearchResult(
        "International cricket run records",
        "https://example.com/cricket",
        "Top batters by international runs",
        "example.com",
    )
    results = WebIntelligenceService._topically_filter_results(
        "top cricket batters international runs",
        [irrelevant, cricket],
    )
    assert results == [cricket]


def test_source_manifest_never_surfaces_adult_result():
    observations = [{
        "action": "web.search",
        "success": True,
        "data": {
            "results": [
                {
                    "title": "XXX videos",
                    "url": "https://bad.example/porn",
                    "snippet": "adult video",
                    "source": "bad.example",
                },
                {
                    "title": "Cricket records",
                    "url": "https://good.example/cricket",
                    "snippet": "international runs",
                    "source": "good.example",
                },
            ]
        }
    }]
    manifest = ConversationSession._source_manifest(observations)
    assert len(manifest) == 1
    assert next(iter(manifest.values()))["url"] == "https://good.example/cricket"
