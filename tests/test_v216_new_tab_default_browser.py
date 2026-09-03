
from pathlib import Path
import pytest
from conduit.conversation import ConversationSession

class Result:
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
        return Result("new focus tab")

    async def new_tab_real_profile(self, *, browser="", private=False):
        self.calls.append(("new_tab_real_profile", browser, private))
        return Result("new real tab", {"browser": browser or "opera gx"})

    async def activate_real_profile(self, *, browser="", private=False, launch_if_missing=True):
        self.calls.append(("activate_real_profile", browser, private, launch_if_missing))
        return Result("activated", {"browser": browser or "opera gx"})

    async def use_default_profile(self, *, browser="", url="about:blank", private=False):
        self.calls.append(("use_default_profile", browser, url, private))
        return Result("selected", {"browser": browser or "opera gx"})
    async def switch_browser(self, name):
        self.calls.append(("switch_browser", name))
        return Result("switched")
    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))
        return Result("new tab")

class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *args, **kwargs):
        raise AssertionError("new-tab command reached AI loop")

class FakeAgent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None

@pytest.mark.asyncio
async def test_plain_new_tab_uses_default_browser():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("new tab")
    assert agent.browser.calls == [("new_tab_focus_only", "")]

@pytest.mark.asyncio
async def test_open_a_new_tab_uses_default_browser():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("open a new tab")
    assert agent.browser.calls == [("new_tab_focus_only", "")]

@pytest.mark.asyncio
async def test_named_browser_still_wins():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("new tab in chrome")
    assert agent.browser.calls == [("new_tab_focus_only", "chrome")]

@pytest.mark.asyncio
async def test_current_browser_keeps_active_session():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("new tab in current browser")
    assert agent.browser.calls == [
        ("new_tab", "about:blank"),
    ]

def test_project_version_is_216():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text()
