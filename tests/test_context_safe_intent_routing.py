
from types import SimpleNamespace

from conduit.conversation import ConversationSession, ConversationTurn


class Agent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=None, model="fake")


def session_with_gpu_history() -> ConversationSession:
    session = ConversationSession(Agent())
    session.history.extend(
        [
            ConversationTurn(
                "Compare RTX 3070 Ti and RX 6700 XT",
                "GPU comparison answer",
            ),
            ConversationTurn(
                "Find their current prices in Pakistan",
                "Price lookup answer",
            ),
        ]
    )
    return session


def test_self_contained_banana_research_ignores_gpu_history():
    session = session_with_gpu_history()
    message = (
        "Tell me three advantages of eating bananas by looking at "
        "studies and research and give me sources"
    )
    assert session._message_needs_history(message) is False
    assert session._route_turn(message) == "tool"
    assert session._conversation_web_actions(message) == {"web.research"}

    goal = session._goal_with_context(message, include_history=False)
    assert "banana" in goal.casefold()
    assert "rtx" not in goal.casefold()
    assert "rx 6700" not in goal.casefold()


def test_weather_after_gpu_topic_routes_web_search_not_price():
    session = session_with_gpu_history()
    message = "What is the weather in Jhelum right now? Do not open a browser."
    assert session._route_turn(message) == "tool"
    assert session._conversation_web_actions(message) == {"web.search"}


def test_python_news_after_gpu_topic_routes_news():
    session = session_with_gpu_history()
    message = "Show me the latest Python news"
    assert session._conversation_web_actions(message) == {"web.news"}


def test_new_product_price_uses_current_product_not_old_gpu_topic():
    session = session_with_gpu_history()
    message = "Find the current price of a PlayStation 5 in Pakistan"
    assert session._conversation_web_actions(message) == {"web.price_search"}
    goal = session._goal_with_context(message, include_history=False)
    assert "playstation 5" in goal.casefold()
    assert "3070" not in goal


def test_referential_followup_uses_history():
    session = session_with_gpu_history()
    message = "Which one is better for ray tracing?"
    assert session._message_needs_history(message) is True
    goal = session._goal_with_context(message, include_history=True)
    assert "RECENT CONVERSATION" in goal
    assert "RTX 3070 Ti" in goal


def test_self_contained_topic_switch_does_not_use_history():
    session = session_with_gpu_history()
    message = "Explain how photosynthesis works"
    assert session._route_turn(message) == "direct"
    assert session._message_needs_history(message) is False
