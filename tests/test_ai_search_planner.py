import pytest

from conduit.conversation import AIIntentRouter, AISearchPlanner
from conduit.core.models import ProviderResponse


class QueueProvider:
    def __init__(self, *responses: str):
        self.responses = list(responses)

    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(text=self.responses.pop(0), model=model)


@pytest.mark.asyncio
async def test_intent_router_understands_misspelled_research_request():
    provider = QueueProvider(
        '''{
          "route":"tool",
          "web_needed":true,
          "browser_requested":false,
          "normalized_request":"Tell me three advantages of eating bananas using studies and research, with sources.",
          "intent":"research health benefits of bananas"
        }'''
    )
    plan = await AIIntentRouter(provider, "fake").plan(
        "tell me 3 advntages banana from studys and give sorces"
    )
    assert plan.route == "tool"
    assert plan.web_needed is True
    assert "bananas" in plan.normalized_request


@pytest.mark.asyncio
async def test_search_planner_disambiguates_python_programming_news():
    provider = QueueProvider(
        '''{
          "action":"web.news",
          "arguments":{"query":"Python programming language developer ecosystem latest news","limit":12,"parallel_queries":3},
          "intent":"technology news",
          "subject":"Python programming language",
          "rewritten_request":"Latest news about the Python programming language and developer ecosystem",
          "answer_style":"concise",
          "sources_requested":false,
          "notes":["Disambiguated Python as the programming language, not the snake"]
        }'''
    )
    plan = await AISearchPlanner(provider, "fake").plan("latest python news")
    assert plan.action == "web.news"
    assert "programming language" in plan.arguments["query"]


@pytest.mark.asyncio
async def test_search_planner_builds_specific_weather_query():
    provider = QueueProvider(
        '''{
          "action":"web.search",
          "arguments":{"query":"current weather Jhelum Pakistan temperature conditions","limit":8,"use_grounding":true,"region":"wt-wt"},
          "intent":"current weather",
          "subject":"Jhelum, Pakistan",
          "rewritten_request":"Current weather in Jhelum, Pakistan",
          "answer_style":"concise",
          "sources_requested":false,
          "notes":[]
        }'''
    )
    plan = await AISearchPlanner(provider, "fake").plan(
        "wats weather jhelum rn dont open browser"
    )
    assert plan.action == "web.search"
    assert "Jhelum Pakistan" in plan.arguments["query"]
    assert "weather" in plan.arguments["query"]


@pytest.mark.asyncio
async def test_search_planner_extracts_product_market_and_currency():
    provider = QueueProvider(
        '''{
          "action":"web.price_search",
          "arguments":{"item":"Sony PlayStation 5","region":"Pakistan","currency":"PKR","limit":10},
          "intent":"current product price",
          "subject":"Sony PlayStation 5",
          "rewritten_request":"Current Sony PlayStation 5 price in Pakistan",
          "answer_style":"concise",
          "sources_requested":false,
          "notes":[]
        }'''
    )
    plan = await AISearchPlanner(provider, "fake").plan(
        "prcie of ps5 in pakstan rn"
    )
    assert plan.action == "web.price_search"
    assert plan.arguments["item"] == "Sony PlayStation 5"
    assert plan.arguments["region"] == "Pakistan"
    assert plan.arguments["currency"] == "PKR"
