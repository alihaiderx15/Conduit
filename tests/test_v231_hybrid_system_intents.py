
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.core.models import ToolCall
from conduit.providers.base import ProviderResponse
from conduit.tools.models import ToolResult


class FakeProvider:
    def __init__(self, text):
        self.text = text
        self.calls = []
    async def chat(self, messages, *, model, tools=()):
        self.calls.append((messages, model))
        return ProviderResponse(text=self.text)


class FakeTools:
    def __init__(self):
        self.calls = []
    async def execute(self, call: ToolCall, *, confirmed=False):
        self.calls.append((call.name, dict(call.arguments), confirmed))
        return ToolResult(True, f"Executed {call.name}.", tool_name=call.name)


class FakeAgent:
    def __init__(self, provider):
        self.loop = SimpleNamespace(provider=provider, model="fake")
        self.tools = FakeTools()
        self.events = None
        self.browser = SimpleNamespace()


@pytest.mark.parametrize("phrase", [
    "turn on wifi",
    "wifi on",
    "turn wifi on",
    "hey conduit turn on wifi",
])
@pytest.mark.asyncio
async def test_wifi_canonical_phrases_bypass_ai(phrase):
    provider = FakeProvider(
        '{"action":"system.wifi_toggle","arguments":{"enabled":false}}'
    )
    agent = FakeAgent(provider)
    session = ConversationSession(agent)

    result = await session._execute_system_control_request(phrase)
    assert result is not None
    assert agent.tools.calls == [
        ("system.wifi_toggle", {"enabled": True}, True)
    ]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_flexible_wireless_wording_uses_ai_then_same_system_tool():
    provider = FakeProvider(
        '{"action":"system.wifi_toggle","arguments":{"enabled":true}}'
    )
    agent = FakeAgent(provider)
    session = ConversationSession(agent)
    phrase = "hey conduit could you enable my wireless connection again"

    assert session._could_be_system_control_request(phrase)
    assert await session._execute_system_control_request(phrase) is None

    plan = await session._make_system_plan(phrase, needs_history=False)
    assert plan is not None
    assert plan.action == "system.wifi_toggle"
    assert plan.arguments == {"enabled": True}

    await session._execute_system_plan(plan)
    assert agent.tools.calls == [
        ("system.wifi_toggle", {"enabled": True}, True)
    ]


@pytest.mark.asyncio
async def test_flexible_brightness_wording_maps_to_structured_action():
    provider = FakeProvider(
        '{"action":"system.brightness_down","arguments":{"step":10}}'
    )
    agent = FakeAgent(provider)
    session = ConversationSession(agent)
    phrase = "can you dim my screen a little"

    assert session._could_be_system_control_request(phrase)
    plan = await session._make_system_plan(phrase, needs_history=False)
    assert plan is not None
    assert plan.action == "system.brightness_down"
    assert plan.arguments == {"step": 10}


@pytest.mark.asyncio
async def test_router_rejects_non_system_action():
    provider = FakeProvider(
        '{"action":"desktop.hotkey","arguments":{"keys":["win","d"]}}'
    )
    agent = FakeAgent(provider)
    session = ConversationSession(agent)
    plan = await session._make_system_plan(
        "could you show my desktop",
        needs_history=False,
    )
    assert plan is None


def test_version_231():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
