
from pathlib import Path
import inspect
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.conversation import ConversationSession


def test_new_tab_focus_only_is_exactly_focus_then_ctrl_t():
    source = inspect.getsource(BrowserEngine.new_tab_focus_only)
    assert 'ensure_native_browser_session' in source
    assert '_native_hotkey("ctrl", "t")' in source
    assert "launch_native" not in source
    assert "maximize_native_session" not in source
    assert "ShowWindow" not in source
    assert "about:blank" not in source


class R:
    def __init__(self, message="ok", data=None):
        self.message = message
        self.data = data or {}
        self.success = True


class FakeBrowser:
    is_started = False
    def __init__(self):
        self.calls = []

    async def new_tab_focus_only(self, *, browser=""):
        self.calls.append(("new_tab_focus_only", browser))
        return R("opened")

    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))
        return R("opened current")


class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *a, **k):
        raise AssertionError("new tab should not reach AI loop")


class Agent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_plain_new_tab_focuses_default_then_ctrl_t_path():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab")
    assert agent.browser.calls == [("new_tab_focus_only", "")]


@pytest.mark.asyncio
async def test_named_new_tab_focuses_named_browser_then_ctrl_t_path():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab in chrome")
    assert agent.browser.calls == [("new_tab_focus_only", "chrome")]


@pytest.mark.asyncio
async def test_current_browser_keeps_current_session_ctrl_t_path():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab in current browser")
    assert agent.browser.calls == [("new_tab", "about:blank")]


def test_project_version_is_221():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
