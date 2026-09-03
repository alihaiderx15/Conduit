
from types import SimpleNamespace
from pathlib import Path
import pytest

from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserDescriptor, BrowserSession
from conduit.tools.registry import ToolRegistry


REQUIRED = {
    "browser.launch_profile",
    "browser.attach_existing",
    "browser.list_sessions",
    "browser.switch_session",
    "browser.new_tab",
    "browser.close_tab",
    "browser.list_tabs",
    "browser.switch_tab",
    "browser.back",
    "browser.forward",
    "browser.reload",
    "browser.screenshot",
    "browser.download",
    "browser.use_default_profile",
}


def test_browser_action_pack_contains_all_requested_session_actions():
    actions = register_default_actions(UnifiedActionRegistry(ToolRegistry()))
    names = {item.name for item in actions.planning_capabilities()}
    assert REQUIRED <= names


def test_browser_policy_defaults_to_real_profile_session():
    from conduit.dynamic_agent.loop import DynamicAgentLoop
    prompt = DynamicAgentLoop._system_prompt(SimpleNamespace())
    assert "browser.use_default_profile" in prompt
    assert "Windows default browser" in prompt
    assert "user explicitly names Chrome" in prompt


@pytest.mark.asyncio
async def test_use_default_profile_uses_default_browser_when_name_omitted(monkeypatch):
    import conduit.browser.engine as engine_mod

    descriptor = BrowserDescriptor(
        "opera", ("opera stable",), "chromium",
        ("opera.exe",), ("C:/fake/opera.exe",), ("--private",),
    )
    calls = []

    monkeypatch.setattr(engine_mod, "default_browser_descriptor", lambda: descriptor)
    monkeypatch.setattr(engine_mod, "launch_native", lambda d, url="", private=False: (
        calls.append((d.name, url, private)) or 1234,
        "C:/fake/opera.exe",
    ))
    monkeypatch.setattr(engine_mod, "focus_native_session", lambda session: True)
    monkeypatch.setattr(BrowserEngine, "state", lambda self, **kwargs: _fake_state())

    engine = BrowserEngine()
    result = await engine.use_default_profile(url="https://example.com")
    assert result.success
    assert calls[0][0] == "opera"
    assert result.data["browser"] == "opera"
    assert result.data["mode"] == "real_profile"


@pytest.mark.asyncio
async def test_named_browser_overrides_default(monkeypatch):
    import conduit.browser.engine as engine_mod

    chrome = BrowserDescriptor(
        "chrome", ("google chrome",), "chromium",
        ("chrome.exe",), ("C:/fake/chrome.exe",), ("--incognito",),
    )
    calls = []
    monkeypatch.setattr(engine_mod, "resolve_descriptor", lambda name: chrome)
    monkeypatch.setattr(engine_mod, "launch_native", lambda d, url="", private=False: (
        calls.append((d.name, private)) or 2222,
        "C:/fake/chrome.exe",
    ))
    monkeypatch.setattr(engine_mod, "focus_native_session", lambda session: True)
    monkeypatch.setattr(BrowserEngine, "state", lambda self, **kwargs: _fake_state())

    engine = BrowserEngine()
    result = await engine.use_default_profile(browser="chrome", private=True)
    assert calls == [("chrome", True)]
    assert result.data["private"] is True


@pytest.mark.asyncio
async def test_multiple_sessions_can_be_listed_and_switched(monkeypatch):
    engine = BrowserEngine()
    one = engine._register_session(BrowserSession(
        "chrome-1", "chrome", "chromium", "real_profile", "native", pid=1
    ))
    two = engine._register_session(BrowserSession(
        "opera-2", "opera", "chromium", "real_profile", "native", pid=2
    ))
    engine._select_session(one)

    monkeypatch.setattr(engine, "_native_focus_or_raise", _noop_focus)
    monkeypatch.setattr(BrowserEngine, "state", lambda self, **kwargs: _fake_state())

    listing = await engine.list_sessions()
    assert len(listing.data["sessions"]) == 2
    switched = await engine.switch_session("opera-2")
    assert switched.data["session_id"] == "opera-2"


@pytest.mark.asyncio
async def test_native_tab_listing_uses_window_title_inventory(monkeypatch):
    engine = BrowserEngine()
    session = engine._register_session(BrowserSession(
        "chrome-1", "chrome", "chromium", "real_profile", "native", pid=1
    ))
    engine._select_session(session)

    titles = ["YouTube - Google Chrome", "Inbox - Google Chrome"]
    cursor = {"i": 0}

    async def fake_focus(session):
        return None

    def fake_hotkey(*keys):
        if keys == ("ctrl", "1"):
            cursor["i"] = 0
        elif keys == ("ctrl", "pagedown"):
            cursor["i"] = (cursor["i"] + 1) % len(titles)

    import conduit.browser.engine as engine_mod
    monkeypatch.setattr(engine, "_native_focus_or_raise", fake_focus)
    monkeypatch.setattr(engine, "_native_hotkey", fake_hotkey)
    monkeypatch.setattr(
        engine_mod,
        "native_window_title",
        lambda s: titles[cursor["i"]],
    )
    monkeypatch.setattr(BrowserEngine, "state", lambda self, **kwargs: _fake_state())

    result = await engine.list_tabs()
    assert result.data["complete"] is True
    assert result.data["inventory"] == "native_window_titles"
    assert [item["index"] for item in result.data["tabs"]] == [1, 2]


def test_browser_descriptors_are_data_driven_not_per_browser_agents():
    from conduit.browser.sessions import BROWSERS
    names = {item.name for item in BROWSERS}
    assert {"chrome", "edge", "firefox", "opera", "opera gx", "brave", "vivaldi", "safari"} <= names
    assert all(item.family in {"chromium", "firefox", "webkit"} for item in BROWSERS)


def test_project_version_is_210():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")


async def _noop_focus(session):
    return None


async def _fake_state():
    from conduit.browser.models import BrowserState
    return BrowserState("Browser", "", "", 0, 0)
