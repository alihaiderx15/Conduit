
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserDescriptor
from conduit.conversation import ConversationSession


class FakeResult:
    def __init__(self, data):
        self.data = data
        self.message = "opened"
        self.success = True


class FakeBrowser:
    is_started = False
    def __init__(self):
        self.calls = []

    async def use_default_profile(self, *, browser="", url="about:blank", private=False):
        self.calls.append((browser, url, private))
        return FakeResult({"browser": browser or "opera gx"})


class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *args, **kwargs):
        raise AssertionError("Simple known-site opens must not reach the generic agent loop.")


class FakeAgent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt", "expected_url"),
    [
        ("open youtube", "https://www.youtube.com"),
        ("open reddit", "https://www.reddit.com"),
        ("open github", "https://github.com"),
        ("open gmail", "https://mail.google.com"),
    ],
)
async def test_simple_site_open_implicitly_uses_default_real_browser(prompt, expected_url):
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask(prompt)
    assert agent.browser.calls == [("", expected_url, False)]
    assert report.status.value == "browser_action"
    assert "Opera GX" in answer


def test_youtube_content_command_is_not_stolen_by_simple_site_router():
    session = ConversationSession(FakeAgent())
    assert not session._could_be_browser_control_request(
        "open youtube and play the latest episode of drama serial Zanjeerain"
    )


@pytest.mark.asyncio
async def test_real_profile_launch_focuses_browser_without_forced_resize(monkeypatch):
    import conduit.browser.engine as engine_mod

    descriptor = BrowserDescriptor(
        "opera gx",
        ("operagx",),
        "chromium",
        ("opera.exe",),
        ("C:/fake/opera.exe",),
        ("--private",),
    )
    events = []

    monkeypatch.setattr(engine_mod, "default_browser_descriptor", lambda: descriptor)
    monkeypatch.setattr(
        engine_mod,
        "launch_native",
        lambda d, url="", private=False: (4321, "C:/fake/opera.exe"),
    )
    monkeypatch.setattr(
        engine_mod,
        "focus_native_session",
        lambda session: events.append(("focus", session.browser_name)) or True,
    )

    async def fake_state(self, **kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("YouTube - Opera GX", "", "", 0, 0)

    monkeypatch.setattr(BrowserEngine, "state", fake_state)

    engine = BrowserEngine()
    result = await engine.use_default_profile(url="https://www.youtube.com")
    assert result.success
    assert ("focus", "opera gx") in events
    assert ("focus", "opera gx") in events
    assert all(item[0] != "maximize" for item in events)


def test_project_version_is_213():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
