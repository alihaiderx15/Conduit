
from types import SimpleNamespace

import pytest

from conduit.conversation.session import ConversationSession
from conduit.conversation.youtube_planner import YouTubePlan


class FakeOutcome:
    def __init__(self, data=None, message="ok", success=True):
        self.success = success
        self.message = message
        self.data = data or {}


class FakeTools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, *, confirmed=False):
        self.calls.append((call.name, dict(call.arguments), confirmed))
        if call.name == "youtube.play":
            return FakeOutcome(
                {"title": "Test Video", "url": "https://www.youtube.com/watch?v=test", "browser_policy": "windows_default"},
                "Opened Test Video in the Windows default browser.",
            )
        if call.name == "youtube.play_latest_upload":
            return FakeOutcome(
                {"title": "Latest Test", "url": "https://www.youtube.com/watch?v=latest", "browser_policy": "windows_default"},
                "Opened latest in the Windows default browser.",
            )
        return FakeOutcome()


class ForbiddenBrowser:
    async def start(self):
        raise AssertionError("Managed Chromium must not be used for visible YouTube playback.")
    async def goto(self, url):
        raise AssertionError("Managed Chromium must not be used for visible YouTube playback.")


class FakeProvider:
    async def chat(self, *args, **kwargs):
        return SimpleNamespace(text="ok")


class FakeAgent:
    def __init__(self):
        self.tools = FakeTools()
        self.browser = ForbiddenBrowser()
        self.loop = SimpleNamespace(provider=FakeProvider(), model="fake")


@pytest.mark.asyncio
async def test_visible_youtube_play_executes_structured_tool_not_browser():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session._execute_youtube_plan(
        "play a test video on YouTube",
        YouTubePlan("youtube.play", {"video": "test video"}),
    )
    assert agent.tools.calls == [
        ("youtube.play", {"video": "test video"}, True)
    ]
    assert "default browser" in answer.casefold()
    assert report.success


@pytest.mark.asyncio
async def test_latest_upload_uses_tool_path_not_managed_browser():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, _ = await session._execute_youtube_plan(
        "play latest upload from aceu",
        YouTubePlan("youtube.play_latest_upload", {"channel": "aceu"}),
    )
    assert agent.tools.calls[0][0] == "youtube.play_latest_upload"
    assert "default browser" in answer.casefold()


def test_youtube_detection_handles_playback_followups():
    agent = FakeAgent()
    session = ConversationSession(agent)
    session.history.append(
        SimpleNamespace(
            user="play an aceu video on YouTube",
            assistant="I opened the video in your default browser.",
        )
    )
    assert session._could_be_youtube_request("pause it")
    assert session._could_be_youtube_request("resume the video")
