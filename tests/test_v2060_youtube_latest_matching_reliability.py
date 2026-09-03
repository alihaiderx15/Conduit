import sys

from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.capabilities import youtube_structured as ys
from conduit.conversation.session import ConversationSession
from conduit.conversation.youtube_planner import YouTubePlan


def test_typo_tolerant_subject_match():
    assert ys._term_matches_haystack("zanjerein", "Zanjeerain Episode 29")
    assert not ys._term_matches_haystack("zanjerein", "Completely Different Drama")


def test_episode_content_prefers_real_episode_over_review():
    real = {"title":"Zanjeerain Episode 29 [Eng Sub]"}
    review = {"title":"New Episode Review Drama Serial Zanjeerain in Urdu-Hindi"}
    assert ys._episode_content_score(real, episode_intent=True) > ys._episode_content_score(review, episode_intent=True)


def test_no_channel_enriches_before_relevance(monkeypatch):
    entries = [
        {"id":"review1","title":"","channel":""},
        {"id":"episode1","title":"","channel":""},
        {"id":"old1","title":"","channel":""},
    ]

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def extract_info(self, target, download=False):
            assert str(target).startswith("ytsearch")
            return {"entries":entries}

    import sys
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))

    monkeypatch.setattr(ys, "_enrich_video_entries", lambda raw, limit=10: [
        ({"id":"review1","title":"New Episode Review Drama Serial Zanjeerain","channel":"Blue Line","timestamp":5000},
         ys.YouTubeVideo("review1","New Episode Review Drama Serial Zanjeerain","https://youtube/review","Blue Line"),5000),
        ({"id":"episode1","title":"Zanjeerain Episode 29 [Eng Sub]","channel":"HUM TV","timestamp":4000},
         ys.YouTubeVideo("episode1","Zanjeerain Episode 29 [Eng Sub]","https://youtube/episode","HUM TV"),4000),
        ({"id":"old1","title":"Zanjeerain Episode 28 [Eng Sub]","channel":"HUM TV","timestamp":1000},
         ys.YouTubeVideo("old1","Zanjeerain Episode 28 [Eng Sub]","https://youtube/old","HUM TV"),1000),
    ])
    result=ys.latest_matching_video("episode of drama serial zanjerein")
    assert result.video_id=="episode1"


def test_channel_scope_can_never_return_other_channel(monkeypatch):
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, target, download=False):
            return {"entries": [{"id":"candidate1"},{"id":"candidate2"}]}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))

    monkeypatch.setattr(ys, "_resolve_channel_identity", lambda c: ("UCARY","ARY Digital","url"))
    monkeypatch.setattr(ys, "_channel_video_entries", lambda c, limit=None: (
        "ARY Digital",
        [{"id":"ary1","title":""},{"id":"ary2","title":""}],
    ))
    monkeypatch.setattr(ys, "_enrich_video_entries", lambda entries, limit=10: [
        ({"id":"ary1","title":"Zanjeerain Episode 50","channel":"ARY Digital","channel_id":"UCARY","timestamp":2000},
         ys.YouTubeVideo("ary1","Zanjeerain Episode 50","u1","ARY Digital"),2000),
        ({"id":"hum1","title":"Zanjeerain Episode 51","channel":"HUM TV","channel_id":"UCHUM","timestamp":5000},
         ys.YouTubeVideo("hum1","Zanjeerain Episode 51","u2","HUM TV"),5000),
    ])
    result=ys.latest_matching_video("episode of drama serial zanjerein", channel="ARY Digital")
    assert result.video_id=="ary1"
    assert result.channel=="ARY Digital"


@pytest.mark.asyncio
async def test_latest_episode_channel_request_bypasses_ai_router(monkeypatch):
    class BrokenProvider:
        async def chat(self,*a,**k):
            raise AssertionError("AI router should not be called for deterministic latest-episode route")
    agent=SimpleNamespace(loop=SimpleNamespace(provider=BrokenProvider(),model="x"))
    session=ConversationSession(agent)
    plan=await session._make_youtube_plan(
        "open youtube and play the latest episode of drama serial Zanjeerain from channel ARY Digital",
        needs_history=False,
    )
    assert plan.action=="youtube.play_latest_matching"
    assert plan.arguments["channel"]=="ARY Digital"
    assert "zanjeerain" in plan.arguments["query"].casefold()
    assert "ary digital" not in plan.arguments["query"].casefold()


def test_project_version_is_2060():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
