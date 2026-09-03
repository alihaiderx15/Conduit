
from pathlib import Path
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserDescriptor
from conduit.conversation import ConversationSession


class R:
    def __init__(self, message="ok", data=None):
        self.message = message
        self.data = data or {}
        self.success = True


@pytest.mark.asyncio
async def test_existing_opera_gx_is_adopted_without_launching_new_window(monkeypatch):
    import conduit.browser.engine as mod

    descriptor = BrowserDescriptor(
        "opera gx", ("operagx",), "chromium",
        ("opera.exe",), ("C:/fake/opera.exe",), ("--private",),
    )
    launches = []

    monkeypatch.setattr(mod, "default_browser_descriptor", lambda: descriptor)
    monkeypatch.setattr(mod, "executable_for", lambda d: "C:/fake/opera.exe")
    monkeypatch.setattr(mod, "focus_native_session", lambda session: True)
    monkeypatch.setattr(
        mod,
        "launch_native",
        lambda *a, **k: launches.append((a, k)) or (999, "C:/fake/opera.exe"),
    )

    async def state(self, **kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("Opera GX", "", "", 0, 0)

    monkeypatch.setattr(BrowserEngine, "state", state)

    engine = BrowserEngine()
    result = await engine.activate_real_profile()

    assert result.success
    assert result.data["browser"] == "opera gx"
    assert launches == []


class FakeBrowser:
    is_started = False

    def __init__(self):
        self.calls = []

    async def new_tab_focus_only(self, *, browser=""):
        self.calls.append(("new_tab_focus_only", browser))
        return R("new focus tab")

    async def new_tab_real_profile(self, *, browser="", private=False):
        self.calls.append(("new_tab_real_profile", browser, private))
        return R("new real tab", {"browser": browser or "opera gx"})

    async def activate_real_profile(
        self, *, browser="", private=False, launch_if_missing=True
    ):
        self.calls.append(("activate", browser, private, launch_if_missing))
        return R("activated", {"browser": browser or "opera gx"})

    async def new_tab(self, url="about:blank"):
        self.calls.append(("new_tab", url))
        return R("new tab")


class ForbiddenLoop:
    provider = None
    model = "fake"

    async def run(self, *a, **k):
        raise AssertionError("new tab reached AI loop")


class Agent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_plain_new_tab_activates_existing_default_browser_before_ctrl_t():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("new tab")

    assert agent.browser.calls == [
        ("new_tab_focus_only", ""),
    ]


def test_project_version_is_217():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
