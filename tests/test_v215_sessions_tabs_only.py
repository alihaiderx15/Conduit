
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserSession
from conduit.conversation import ConversationSession


class Result:
    def __init__(self, message="ok", data=None):
        self.message = message
        self.data = data or {}
        self.success = True


def test_native_session_registry_reuses_same_logical_id():
    engine = BrowserEngine()
    a = engine._register_session(BrowserSession(
        "opera-gx-1", "opera gx", "chromium", "real_profile", "native",
        private=False, pid=1,
    ))
    b = engine._register_session(BrowserSession(
        "opera-gx-2", "opera gx", "chromium", "real_profile", "native",
        private=False, pid=2,
    ))
    assert a.session_id == "opera-gx-1"
    assert b.session_id == "opera-gx-1"
    assert list(engine._sessions) == ["opera-gx-1"]
    assert engine._sessions["opera-gx-1"].pid == 2


def test_private_and_normal_native_sessions_remain_separate():
    engine = BrowserEngine()
    normal = engine._register_session(BrowserSession(
        "chrome-1", "chrome", "chromium", "real_profile", "native",
        private=False, pid=1,
    ))
    private = engine._register_session(BrowserSession(
        "chrome-2", "chrome", "chromium", "real_profile_private", "native",
        private=True, pid=2,
    ))
    assert len(engine._sessions) == 2
    assert normal.session_id != private.session_id



@pytest.mark.asyncio
async def test_native_numeric_tabs_are_one_based(monkeypatch):
    engine = BrowserEngine()
    session = engine._register_session(BrowserSession(
        "opera-gx-1", "opera gx", "chromium", "real_profile", "native", pid=1
    ))
    engine._select_session(session)

    tabs = [
        {"index": 1, "title": "One", "url": "", "window_hwnd": 100, "window_pid": 1, "window_tab_order": 1},
        {"index": 2, "title": "Two", "url": "", "window_hwnd": 100, "window_pid": 1, "window_tab_order": 2},
        {"index": 3, "title": "Three", "url": "", "window_hwnd": 100, "window_pid": 1, "window_tab_order": 3},
    ]
    activated = []

    async def collect(_):
        return tabs

    async def activate(_, item):
        activated.append(item["index"])

    async def state(**kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("Three", "", "", 0, 0)

    monkeypatch.setattr(engine, "_native_collect_all_tabs", collect)
    monkeypatch.setattr(engine, "_native_activate_inventory_tab", activate)
    monkeypatch.setattr(engine, "state", state)

    await engine.switch_tab(3)
    assert activated == [3]


@pytest.mark.asyncio
async def test_native_named_tab_switch_uses_window_titles(monkeypatch):
    import conduit.browser.engine as module

    engine = BrowserEngine()
    session = engine._register_session(BrowserSession(
        "chrome-1", "chrome", "chromium", "real_profile", "native", pid=1
    ))
    engine._select_session(session)

    titles = ["YouTube - Google Chrome", "Gmail - Google Chrome", "GitHub - Google Chrome"]
    pos = {"i": 0}

    async def focus(_): return None
    def hotkey(*keys):
        if keys == ("ctrl", "1"):
            pos["i"] = 0
        elif keys == ("ctrl", "pagedown"):
            pos["i"] = (pos["i"] + 1) % len(titles)
    async def state(**kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState(titles[pos["i"]], "", "", 0, 0)

    monkeypatch.setattr(engine, "_native_focus_or_raise", focus)
    monkeypatch.setattr(engine, "_native_hotkey", hotkey)
    monkeypatch.setattr(engine, "state", state)
    monkeypatch.setattr(module, "native_window_title", lambda _: titles[pos["i"]])

    await engine.switch_tab("Gmail")
    assert pos["i"] == 1


class FakeBrowser:
    is_started = False

    def __init__(self):
        self.calls = []
    async def ensure_native_browser_session(self, *, browser=""):
        self.calls.append(("ensure", browser))
        return object()

    async def switch_session(self, session_id):
        self.calls.append(("switch_session", session_id))
        return Result("switched")

    async def switch_browser(self, name):
        self.calls.append(("switch_browser", name))
        return Result("browser selected")

    async def switch_tab(self, tab):
        self.calls.append(("switch_tab", tab))
        return Result("tab switched")

    async def list_tabs(self):
        self.calls.append(("list_tabs", None))
        return Result("tabs", {"tabs":[
            {"index":1,"title":"YouTube","active":True},
            {"index":2,"title":"Gmail","active":False},
        ]})

    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))
        return Result("new tab")

    async def close_tab(self, tab=None):
        self.calls.append(("close_tab", tab))
        return Result("closed")

    async def close_all_tabs(self):
        self.calls.append(("close_all_tabs", None))
        return Result("closed all")

    async def attach_existing(self, browser="", endpoint=""):
        self.calls.append(("attach_existing", browser))
        return Result("attached")


class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *args, **kwargs):
        raise AssertionError("session/tab command should not reach AI loop")


class FakeAgent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_switch_session_exact_phrase_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("switch to browser session chrome-1")
    assert agent.browser.calls == [("switch_session", "chrome-1")]


@pytest.mark.asyncio
async def test_browser_qualified_tab_switch_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("switch to opera gx tab 3")
    assert agent.browser.calls == [
        ("ensure", "opera gx"),
        ("switch_tab", 3),
    ]


@pytest.mark.asyncio
async def test_named_tab_switch_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("switch to tab Gmail")
    assert agent.browser.calls == [("ensure", ""), ("switch_tab", "Gmail")]


@pytest.mark.asyncio
async def test_list_browser_tabs_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, _ = await session.ask("list browser tabs")
    assert agent.browser.calls == [("ensure", ""), ("list_tabs", None)]
    assert "YouTube" in answer and "Gmail" in answer


@pytest.mark.asyncio
async def test_close_tab_4_and_close_all_tabs_are_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("close tab 4")
    assert agent.browser.calls == [("ensure", ""), ("close_tab", 4)]

    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("close all tabs")
    assert agent.browser.calls == [("ensure", ""), ("close_all_tabs", None)]


@pytest.mark.asyncio
async def test_attach_existing_chrome_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("attach to my existing chrome browser")
    assert agent.browser.calls == [("attach_existing", "chrome")]


def test_project_version_is_215():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
