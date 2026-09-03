
from types import SimpleNamespace

import pytest

from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.conversation import ConversationSession
from conduit.tools.builtin import registry as tool_registry
from conduit.web_intelligence.models import SearchResult
from conduit.web_intelligence.service import WebIntelligenceService


class FakeBrowser:
    def __init__(self, started=False):
        self.is_started = started
        self.calls = []

    async def start(self):
        self.calls.append(("start", None))
        self.is_started = True

    async def goto(self, url):
        self.calls.append(("goto", url))

    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))


class FakeEvents:
    async def emit(self, *args, **kwargs):
        return None


class FakeAgent:
    def __init__(self, started=False):
        self.browser = FakeBrowser(started)
        self.events = FakeEvents()
        self.loop = SimpleNamespace(provider=None, model="fake")


def test_weather_lookup_routes_to_browser_but_climate_research_does_not():
    assert ConversationSession._is_weather_browser_lookup(
        "what is the weather in Jhelum right now"
    )
    assert not ConversationSession._is_weather_browser_lookup(
        "research historical weather trends in Jhelum"
    )


@pytest.mark.asyncio
async def test_weather_uses_default_browser_action():
    class Tools:
        def __init__(self):
            self.calls = []
        async def execute(self, call, *, confirmed=False):
            self.calls.append((call.name, dict(call.arguments), confirmed))
            return SimpleNamespace(success=True, message="ok")

    agent = FakeAgent(False)
    agent.tools = Tools()
    session = ConversationSession(agent)
    answer = await session._open_weather_in_browser(
        "current weather in Jhelum Pakistan"
    )
    assert agent.tools.calls[0][0] == "system.open_url"
    assert agent.tools.calls[0][2] is True
    assert "default browser" in answer.casefold()



def test_exact_spec_verification_is_strict():
    assert ConversationSession._strict_verification_requested(
        "Compare exact VRAM memory bus and power and verify with sources"
    )
    assert not ConversationSession._strict_verification_requested(
        "Compare these GPUs for gaming"
    )


def test_academic_research_filter_rejects_dictionary_and_reddit():
    prefs = ["academic", "medical", "review"]
    dictionary = SearchResult(
        "Benefit definition",
        "https://dictionary.cambridge.org/dictionary/english/benefit",
        "Definition of benefit",
        "dictionary.cambridge.org",
    )
    reddit = SearchResult(
        "Banana discussion",
        "https://reddit.com/r/nutrition/x",
        "People discuss bananas",
        "reddit.com",
    )
    pubmed = SearchResult(
        "Banana nutrition review",
        "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "Review of banana nutrition",
        "pubmed.ncbi.nlm.nih.gov",
    )
    assert not WebIntelligenceService._research_source_quality(dictionary, prefs)
    assert not WebIntelligenceService._research_source_quality(reddit, prefs)
    assert WebIntelligenceService._research_source_quality(pubmed, prefs)


def test_research_topic_filter_rejects_unrelated_result():
    unrelated = SearchResult(
        "Introducing ChatGPT",
        "https://openai.com/index/chatgpt/",
        "Conversational AI",
        "openai.com",
    )
    relevant = SearchResult(
        "Banana nutrition review",
        "https://example.edu/banana-review",
        "Banana consumption and nutrition",
        "example.edu",
    )
    query = "health benefits of bananas scientific studies"
    assert not WebIntelligenceService._result_topic_relevant(query, unrelated)
    assert WebIntelligenceService._result_topic_relevant(query, relevant)


def test_browser_new_tab_is_registered():
    actions = register_default_actions(UnifiedActionRegistry(tool_registry))
    assert "browser.new_tab" in {item.name for item in actions.all()}
