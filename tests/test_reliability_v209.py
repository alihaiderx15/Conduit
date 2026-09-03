
from types import SimpleNamespace

from conduit.conversation import ConversationSession
from conduit.conversation.search_planner import IntentPlan


class DummyAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=None, model="fake")


def test_research_words_force_research():
    assert ConversationSession._required_web_actions(
        "tell me benefits of bananas using studies and research and give sources"
    ) == {"web.research"}


def test_weather_forces_live_search():
    assert ConversationSession._required_web_actions(
        "wats weather jhelum rn dont open browser"
    ) == {"web.search"}


def test_price_forces_price_search():
    assert ConversationSession._required_web_actions(
        "find prcie of ps5 price in pakistan rn"
    ) == {"web.price_search"}


def test_news_forces_news():
    assert ConversationSession._required_web_actions(
        "show me latest python news"
    ) == {"web.news"}


def test_plain_comparison_does_not_force_web():
    assert ConversationSession._required_web_actions(
        "Compare RTX 3070 Ti and RX 6700 XT"
    ) == set()
