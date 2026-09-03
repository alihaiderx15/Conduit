
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.browser import sessions as bs
from conduit.conversation import ConversationSession


def test_default_browser_prefers_exact_installed_opera_gx_path(monkeypatch):
    gx = bs.resolve_descriptor("opera gx")
    opera = bs.resolve_descriptor("opera")

    monkeypatch.setattr(
        bs,
        "_windows_default_browser_command",
        lambda: r'"C:\Users\Ali\AppData\Local\Programs\Opera GX\opera.exe" --single-argument %1',
    )

    def fake_exec(descriptor):
        if descriptor.name == "opera gx":
            return r"C:\Users\Ali\AppData\Local\Programs\Opera GX\opera.exe"
        if descriptor.name == "opera":
            return None
        return None

    monkeypatch.setattr(bs, "executable_for", fake_exec)
    result = bs.default_browser_descriptor()
    assert result.name == "opera gx"


def test_specific_opera_gx_signature_beats_plain_opera(monkeypatch):
    monkeypatch.setattr(
        bs,
        "_windows_default_browser_command",
        lambda: r'"C:\Users\Ali\AppData\Local\Programs\Opera GX\launcher.exe" "%1"',
    )
    monkeypatch.setattr(bs, "executable_for", lambda descriptor: None)
    assert bs.default_browser_descriptor().name == "opera gx"


def test_incognito_browser_modifier_is_not_part_of_open_subject():
    assert ConversationSession._browser_open_subject(
        "open youtube in chrome incognito"
    ) == "youtube"
    assert ConversationSession._browser_open_subject(
        "open gmail in chrome private mode"
    ) == "gmail"


def test_browser_display_name_preserves_gx_capitalization():
    assert ConversationSession._browser_display_name("opera gx") == "Opera GX"


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
        raise AssertionError("Browser command should not reach the agent loop.")


class FakeAgent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_open_youtube_in_chrome_incognito_opens_youtube_not_search_phrase():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask("open youtube in chrome incognito")
    assert agent.browser.calls == [
        ("chrome", "https://www.youtube.com", True)
    ]
    assert "youtube" in answer.casefold()
    assert "in chrome in chrome" not in answer.casefold()
    assert report.status.value == "browser_action"


def test_project_version_is_212():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
