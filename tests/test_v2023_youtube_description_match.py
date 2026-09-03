
from types import SimpleNamespace

import pytest

from conduit.conversation.session import ConversationSession
from conduit.conversation.youtube_planner import YouTubePlan, _ALLOWED


def test_matching_action_is_allowed():
    assert "youtube.play_matching_video" in _ALLOWED


def test_fallback_detects_remembered_video_description():
    plan = ConversationSession._fallback_youtube_plan(
        "I saw a video where people competed for a mansion and the last one there wins"
    )
    assert plan is not None
    assert plan.action == "youtube.play_matching_video"
    assert "mansion" in plan.arguments["description"]


class Outcome:
    def __init__(self, success=True, data=None, message="ok"):
        self.success = success
        self.data = data or {}
        self.message = message


class Tools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, *, confirmed=False):
        self.calls.append((call.name, dict(call.arguments)))
        if call.name == "youtube.search":
            return Outcome(data={
                "videos": [
                    {
                        "title": "Unrelated Challenge",
                        "channel": "Other",
                        "url": "https://www.youtube.com/watch?v=aaaaaa1",
                    },
                    {
                        "title": "Last To Leave Mansion, Keeps It",
                        "channel": "MrBeast",
                        "url": "https://www.youtube.com/watch?v=bbbbbb2",
                    },
                ]
            })
        if call.name == "youtube.play":
            return Outcome(data={
                "title": "Last To Leave Mansion, Keeps It",
                "url": call.arguments["video"],
                "browser_policy": "windows_default",
            })
        raise AssertionError(call.name)


class Provider:
    async def chat(self, messages, model=None):
        return SimpleNamespace(text='{"index":2,"reason":"mansion challenge","confidence":0.98}')


class Agent:
    def __init__(self):
        self.tools = Tools()
        self.loop = SimpleNamespace(provider=Provider(), model="fake")


@pytest.mark.asyncio
async def test_description_match_reranks_then_plays_selected_url():
    agent = Agent()
    session = ConversationSession(agent)
    answer, report = await session._execute_youtube_description_match(
        "I saw a video where people compete for a mansion and last one wins",
        YouTubePlan(
            "youtube.play_matching_video",
            {
                "description": "people compete for a mansion and last one wins",
                "search_query": "mansion last to leave challenge",
                "channel": "MrBeast",
            },
        ),
    )
    assert agent.tools.calls[0][0] == "youtube.search"
    assert agent.tools.calls[1] == (
        "youtube.play",
        {"video": "https://www.youtube.com/watch?v=bbbbbb2"},
    )
    assert "closest match" in answer.casefold()
    assert "default browser" in answer.casefold()
    assert report.success


def test_matching_tool_is_registered():
    from conduit.tools.builtin import registry
    assert registry.get("youtube.play_matching_video").name == "youtube.play_matching_video"
