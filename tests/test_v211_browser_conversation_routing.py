
from types import SimpleNamespace
from urllib.parse import unquote_plus, urlparse, parse_qs
import pytest

from conduit.conversation import ConversationSession


class FakeResult:
    def __init__(self, message="ok", data=None):
        self.message = message
        self.data = data or {}
        self.success = True


class FakeBrowser:
    is_started = False
    def __init__(self):
        self.calls = []

    async def installed(self):
        self.calls.append(("installed", {}))
        return FakeResult("installed", {
            "browsers": [
                {"name":"chrome","family":"chromium","executable":"chrome.exe"},
                {"name":"opera","family":"chromium","executable":"opera.exe"},
            ],
            "default_browser":"opera",
        })

    async def use_default_profile(self, *, browser="", url="about:blank", private=False):
        self.calls.append(("use_default_profile", {
            "browser":browser, "url":url, "private":private
        }))
        return FakeResult("opened", {
            "browser": browser or "opera",
            "mode":"real_profile",
            "transport":"native",
        })

    async def list_sessions(self):
        self.calls.append(("list_sessions", {}))
        return FakeResult("sessions", {"sessions":[]})


class ForbiddenLoop:
    provider = None
    model = "fake"
    async def run(self, *args, **kwargs):
        raise AssertionError("Deterministic browser request must not reach the agent loop.")


class FakeAgent:
    def __init__(self):
        self.browser = FakeBrowser()
        self.loop = ForbiddenLoop()
        self.events = None


@pytest.mark.asyncio
async def test_installed_browser_question_returns_deterministic_browser_result():
    session = ConversationSession(FakeAgent())
    answer, report = await session.ask(
        "tell me what browsers are installed on my pc and which one is my default browser"
    )
    assert "Chrome" in answer
    assert "Opera" in answer
    assert "default browser is Opera" in answer
    assert report.status.value == "browser_action"


@pytest.mark.asyncio
async def test_open_youtube_in_my_browser_is_not_youtube_content_action():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask("open youtube in my browser")
    assert agent.browser.calls == [(
        "use_default_profile",
        {"browser":"", "url":"https://www.youtube.com", "private":False},
    )]
    assert "youtube" in answer.casefold()
    assert report.status.value == "browser_action"


@pytest.mark.asyncio
async def test_open_youtube_in_chrome_uses_real_chrome_profile_not_conduit_profile():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, _ = await session.ask("open youtube in chrome")
    action, args = agent.browser.calls[0]
    assert action == "use_default_profile"
    assert args["browser"] == "chrome"
    assert args["url"] == "https://www.youtube.com"


@pytest.mark.asyncio
async def test_open_gmail_in_default_browser_uses_real_profile():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("open gmail in my default browser")
    action, args = agent.browser.calls[0]
    assert action == "use_default_profile"
    assert args["browser"] == ""
    assert args["url"] == "https://mail.google.com"


@pytest.mark.asyncio
async def test_search_in_my_browser_opens_visible_google_search_not_web_search():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask("search what panadol is used for in my browser")
    action, args = agent.browser.calls[0]
    assert action == "use_default_profile"
    parsed = urlparse(args["url"])
    assert parsed.netloc == "www.google.com"
    query = parse_qs(parsed.query)["q"][0]
    assert query == "what panadol is used for"
    assert "searched for what panadol is used for" in answer.casefold()
    assert report.status.value == "browser_action"


@pytest.mark.asyncio
async def test_private_named_browser_is_preserved():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("open youtube in chrome incognito")
    _, args = agent.browser.calls[0]
    assert args["browser"] == "chrome"
    assert args["private"] is True
