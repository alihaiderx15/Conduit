
from pathlib import Path
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserDescriptor
from conduit.conversation import ConversationSession


class Result:
    def __init__(self, message="ok", data=None):
        self.message = message
        self.data = data or {}
        self.success = True


@pytest.mark.asyncio
async def test_new_tab_real_profile_uses_explicit_about_blank_native_handoff(monkeypatch):
    import conduit.browser.engine as mod

    descriptor = BrowserDescriptor(
        "opera gx", ("operagx",), "chromium",
        ("opera.exe",), ("C:/fake/opera.exe",), ("--private",),
    )
    calls = []

    monkeypatch.setattr(mod, "default_browser_descriptor", lambda: descriptor)
    monkeypatch.setattr(
        mod,
        "launch_native",
        lambda d, url="", private=False: (
            calls.append((d.name, url, private)) or 4444,
            "C:/fake/opera.exe",
        ),
    )

    engine = BrowserEngine()
    result = await engine.new_tab_real_profile()

    assert result.success
    assert calls == [("opera gx", "about:blank", False)]
    assert result.data["browser"] == "opera gx"


class FakeBrowser:
    is_started = False
    def __init__(self):
        self.calls = []

    async def new_tab_focus_only(self, *, browser=""):
        self.calls.append(("new_tab_focus_only", browser))
        return Result("new focus tab")

    async def new_tab_real_profile(self, *, browser="", private=False):
        self.calls.append(("new_tab_real_profile", browser, private))
        return Result("new real tab")

    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))
        return Result("new current tab")


class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *a, **k):
        raise AssertionError("new tab must not reach AI loop")


class Agent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_plain_new_tab_uses_real_profile_handoff():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab")
    assert agent.browser.calls == [
        ("new_tab_focus_only", "")
    ]


@pytest.mark.asyncio
async def test_named_new_tab_uses_named_real_profile_handoff():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab in chrome")
    assert agent.browser.calls == [
        ("new_tab_focus_only", "chrome")
    ]


@pytest.mark.asyncio
async def test_current_browser_new_tab_keeps_ctrl_t_path():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab in current browser")
    assert agent.browser.calls == [
        ("new_tab", "about:blank")
    ]


def test_project_version_is_220():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
