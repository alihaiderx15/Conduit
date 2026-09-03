
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession


def bare_session():
    session = object.__new__(ConversationSession)
    session.history = []
    session._max_history_turns = 8
    session._dev_context = {}
    session._code_context = {}
    session._file_context = {}
    session._messaging_context = {}
    return session


def test_song_is_youtube_request():
    session = bare_session()
    assert session._could_be_youtube_request("play the song mera piya ghar aya")
    assert session._could_be_youtube_request("play music believer")


def test_song_fallback_is_matching_video():
    plan = ConversationSession._fallback_youtube_plan("play the song mera piya ghar aya")
    assert plan is not None
    assert plan.action == "youtube.play_matching_video"
    assert plan.arguments["search_query"].casefold() == "mera piya ghar aya"


@pytest.mark.asyncio
async def test_song_bypasses_ai_youtube_router(monkeypatch):
    session = bare_session()
    class ExplodingRouter:
        def __init__(self, *args, **kwargs):
            raise AssertionError("AI router should not be used for direct song playback")
    from conduit.conversation import session as session_mod
    monkeypatch.setattr(session_mod, "AIYouTubeRouter", ExplodingRouter)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=object(), model="unused"))
    plan = await session._make_youtube_plan("play the song mera piya ghar aya", needs_history=False)
    assert plan.action == "youtube.play_matching_video"


def test_planned_project_is_preserved_for_yes_continuation():
    root = Path(__file__).resolve().parents[1]
    src = (root/"conduit/conversation/session.py").read_text(encoding="utf-8")
    assert 'self._dev_context["pending_plan"]' in src
    assert "Build this planned project now? Type YES" in src
    assert "generate_project_files(request, plan)" in src


def test_version_281():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
