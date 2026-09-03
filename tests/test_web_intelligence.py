
import asyncio

import httpx
import pytest

from conduit.tools.builtin import registry
from conduit.web_intelligence import WebIntelligenceService, UnsafeSearchQueryError
from conduit.web_intelligence.service import _decode_duck_url


DUCK_HTML = """
<html><body>
<div class="result">
  <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha">Alpha laptop result</a>
  <a class="result__snippet">Useful alpha evidence with price $499.99.</a>
</div>
<div class="result">
  <a class="result__a" href="https://example.org/beta">Beta result</a>
  <a class="result__snippet">Useful beta evidence.</a>
</div>
</body></html>
"""

NEWS_XML = """<?xml version="1.0"?>
<rss><channel>
<item>
<title>Alpha News</title>
<link>https://news.example/alpha</link>
<description><![CDATA[Latest <b>alpha</b> update.]]></description>
<pubDate>Thu, 06 Aug 2026 10:00:00 GMT</pubDate>
<source>Example News</source>
</item>
</channel></rss>
"""


def handler(request: httpx.Request) -> httpx.Response:
    if "duckduckgo.com" in request.url.host:
        return httpx.Response(200, text=DUCK_HTML)
    if "news.google.com" in request.url.host:
        return httpx.Response(200, content=NEWS_XML.encode(), headers={"content-type": "application/rss+xml"})
    if "bing.com" in request.url.host:
        return httpx.Response(
            200,
            content=b"""<?xml version="1.0"?><rss><channel><item>
            <title>Bing fallback</title>
            <link>https://bing.example/result</link>
            <description>Bing fallback evidence.</description>
            </item></channel></rss>""",
            headers={"content-type": "application/rss+xml"},
        )
    if "wikipedia.org" in request.url.host:
        return httpx.Response(
            200,
            json={
                "query": {
                    "search": [
                        {
                            "title": "Alpha",
                            "snippet": "Alpha encyclopedia evidence",
                        }
                    ]
                }
            },
        )
    if "example.com" in request.url.host or "example.org" in request.url.host:
        return httpx.Response(200, text="<html><body>Long source evidence about alpha.</body></html>", headers={"content-type": "text/html"})
    raise AssertionError(f"Unexpected URL: {request.url}")


@pytest.fixture
def service():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    instance = WebIntelligenceService(client=client, gemini_api_key="")
    yield instance
    asyncio.run(client.aclose())


@pytest.mark.asyncio
async def test_search_fallback_returns_structured_results(service):
    response = await service.search("alpha", use_grounding=False)
    assert response.provider == "duckduckgo"
    assert response.results[0].title == "Alpha laptop result"
    assert response.results[0].url == "https://example.com/alpha"


@pytest.mark.asyncio
async def test_parallel_news_is_deduplicated(service):
    response = await service.news("alpha", parallel_queries=3)
    assert response.provider == "google-news-rss"
    assert len(response.results) == 1
    assert response.results[0].source == "Example News"


@pytest.mark.asyncio
async def test_price_search_extracts_visible_price(service):
    response = await service.price_search("alpha laptop")
    assert response.results[0].price == "$499.99"


@pytest.mark.asyncio
async def test_research_fallback_collects_sources(service):
    response = await service.research("alpha", use_grounding=False, depth=1)
    assert response.sources
    assert "Research evidence collected" in response.answer


@pytest.mark.asyncio
async def test_compare_runs_multiple_item_searches(service):
    response = await service.compare(["alpha", "beta"], criteria=["battery"])
    assert response.mode == "compare"
    assert response.metadata["parallel"] is True
    assert set(response.metadata["comparison"]) == {"alpha", "beta"}


def test_restricted_purchase_query_is_blocked(service):
    with pytest.raises(UnsafeSearchQueryError):
        asyncio.run(service.search("where to buy a gun", use_grounding=False))


def test_web_actions_are_registered():
    names = {item.name for item in registry.all()}
    assert {"web.search", "web.news", "web.research", "web.price_search", "web.compare"} <= names


def test_duck_redirect_decode():
    value = _decode_duck_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx")
    assert value == "https://example.com/x"


@pytest.mark.asyncio
async def test_search_reports_missing_grounding_key(service):
    response = await service.search("alpha", use_grounding=True)
    assert response.metadata["grounding_requested"] is True
    assert response.metadata["grounding_available"] is False
    assert "GEMINI_API_KEY" in response.metadata["grounding_error"]


@pytest.mark.asyncio
async def test_public_search_uses_bing_when_duck_returns_empty():
    calls = {"duck": 0}

    def empty_duck_handler(request: httpx.Request) -> httpx.Response:
        if "duckduckgo.com" in request.url.host:
            calls["duck"] += 1
            return httpx.Response(200, text="<html><body></body></html>")
        if "bing.com" in request.url.host:
            return httpx.Response(
                200,
                content=b"""<?xml version="1.0"?><rss><channel><item>
                <title>Bing result</title>
                <link>https://example.com/bing</link>
                <description>Fallback evidence.</description>
                </item></channel></rss>""",
            )
        raise AssertionError(str(request.url))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(empty_duck_handler)
    )
    service = WebIntelligenceService(client=client, gemini_api_key="")
    try:
        response = await service.search("alpha", use_grounding=False)
        assert calls["duck"] == 2
        assert response.provider == "bing-rss"
        assert response.results[0].title == "Bing result"
    finally:
        await client.aclose()
