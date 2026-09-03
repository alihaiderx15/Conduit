
from types import SimpleNamespace
import pytest

from conduit.conversation import ConversationSession
from conduit.core.models import ProviderResponse


class Provider:
    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(text="DIRECT MODEL ANSWER", model=model)


class Agent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=Provider(), model="fake")
        self.calls = []

    async def run(self, goal, *, initial_variables=None, allowed_actions=None):
        self.calls.append((goal, allowed_actions))
        return SimpleNamespace(
            status=SimpleNamespace(value="completed"),
            success=True,
            iterations=1,
            final_message="done",
            observations=(),
        )


def session():
    return ConversationSession(Agent())


def test_plain_gpu_comparison_routes_direct():
    s = session()
    assert s._route_turn("Compare RTX 3070 Ti and RX 6700 XT") == "direct"


def test_comparison_with_sources_routes_hybrid():
    s = session()
    assert s._route_turn(
        "Compare RTX 3070 Ti and RX 6700 XT and give sources"
    ) == "hybrid"


def test_comparison_with_current_price_routes_hybrid():
    s = session()
    assert s._route_turn(
        "Compare RTX 3070 Ti and RX 6700 XT and tell me current price in Pakistan"
    ) == "hybrid"


def test_current_weather_routes_tool():
    s = session()
    assert s._route_turn("What is the weather in Jhelum right now?") == "tool"


def test_price_action_beats_compare_when_both_are_present():
    s = session()
    assert s._conversation_web_actions(
        "Compare RTX 3070 Ti and RX 6700 XT current price in Pakistan"
    ) == {"web.price_search"}


@pytest.mark.asyncio
async def test_direct_answer_skips_agent_action_loop():
    s = session()
    answer, report = await s.ask("Compare RTX 3070 Ti and RX 6700 XT")
    assert answer == "DIRECT MODEL ANSWER"
    assert report.status.value == "direct_answer"
    assert s.agent.calls == []
