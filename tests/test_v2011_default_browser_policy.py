
import asyncio
from types import SimpleNamespace

import pytest

from conduit.conversation import ConversationSession


class FakeOutcome:
    def __init__(self, success=True, message="ok"):
        self.success = success
        self.message = message


class FakeTools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, *, confirmed=False):
        self.calls.append((call.name, dict(call.arguments), confirmed))
        return FakeOutcome()


class ForbiddenManagedBrowser:
    is_started = False
    async def start(self):
        raise AssertionError("Visible browsing must not start Playwright.")
    async def goto(self, url):
        raise AssertionError("Visible browsing must not navigate Playwright.")
    async def new_tab(self, url="about:blank"):
        raise AssertionError("Visible browsing must not use a managed browser tab.")


class FakeEvents:
    async def emit(self, *args, **kwargs):
        pass


class FakeAgent:
    def __init__(self):
        self.tools = FakeTools()
        self.browser = ForbiddenManagedBrowser()
        self.events = FakeEvents()
        self.loop = SimpleNamespace(provider=None, model="fake")


@pytest.mark.asyncio
async def test_weather_uses_windows_default_browser_action_only():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer = await session._open_weather_in_browser("Jhelum Pakistan weather")
    assert len(agent.tools.calls) == 1
    action, arguments, confirmed = agent.tools.calls[0]
    assert action == "system.open_url"
    assert confirmed is True
    assert arguments["url"].startswith("https://www.google.com/search?")
    assert "default browser" in answer.casefold()


def test_dynamic_agent_prompt_contains_visible_browser_policy():
    from conduit.dynamic_agent.loop import DynamicAgentLoop
    text = DynamicAgentLoop._system_prompt(SimpleNamespace())
    assert "VISIBLE BROWSER POLICY" in text
    assert "system.open_url" in text
    assert "configured default browser" in text
