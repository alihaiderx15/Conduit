import sys

from pathlib import Path
import pytest
from types import SimpleNamespace

from conduit.messaging import service as ms
from conduit.capabilities import youtube_structured as ys
from conduit.conversation.session import ConversationSession


@pytest.mark.asyncio
async def test_whatsapp_compact_readiness_accepts_loaded_shell(monkeypatch):
    async def fake_desc(agent, prompt):
        assert "WhatsApp" in prompt
        assert "CURRENT" in prompt or "RIGHT NOW" in prompt
        return SimpleNamespace(description="READY\nChat list and message composer are visible.")
    monkeypatch.setattr(ms, "observe_messaging_description", fake_desc)
    state, reason = await ms.classify_whatsapp_ready_compact(SimpleNamespace())
    assert state == "ready"


def test_whatsapp_wait_loop_uses_compact_probe_immediately_and_one_second_poll():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def wait_until_client_ready"):source.index("async def active_window_identity")]
    assert 'if service == "whatsapp":' in block
    assert "classify_whatsapp_ready_compact" in block
    session_source = (Path(__file__).resolve().parents[1]/"conduit"/"conversation"/"session.py").read_text(encoding="utf-8")
    prep = session_source[session_source.index("async def _prepare_messaging_client"):session_source.index("async def _resolve_messaging_contact")]
    assert "poll_seconds=1.0" in prep


def test_latest_match_terms_keep_subject_and_drop_generic_episode_words():
    terms = ys._latest_match_terms("latest episode of drama serial Zanjerein")
    assert "zanjerein" in terms
    assert "latest" not in terms
    assert "episode" not in terms
    assert "drama" not in terms
    assert "serial" not in terms


def test_latest_matching_no_channel_chooses_newest_relevant(monkeypatch):
    entries = [
        {"id":"a123456","title":"Zanjerein Episode 10","channel":"Channel A"},
        {"id":"b123456","title":"Zanjerein Episode 9","channel":"Channel B"},
        {"id":"c123456","title":"Zanjerein Episode 8","channel":"Channel C"},
    ]

    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def extract_info(self, target, download=False):
            if str(target).startswith("ytsearch"):
                return {"entries": entries}
            vid = str(target).split("v=")[-1]
            stamps = {"a123456": 2000, "b123456": 1000, "c123456": 500}
            return {
                "id":vid,
                "title":next(e["title"] for e in entries if e["id"]==vid),
                "webpage_url":"https://www.youtube.com/watch?v="+vid,
                "channel":next(e["channel"] for e in entries if e["id"]==vid),
                "timestamp":stamps[vid],
            }

    import sys, types
    fake_module = types.SimpleNamespace(YoutubeDL=FakeYDL)
    monkeypatch.setitem(sys.modules, "yt_dlp", fake_module)
    result = ys.latest_matching_video("latest episode of drama serial zanjerein")
    assert result.video_id == "a123456"


def test_latest_matching_channel_scope_never_uses_other_channel(monkeypatch):
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, target, download=False):
            return {"entries": [{"id":"candidate1"},{"id":"candidate2"}]}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))

    monkeypatch.setattr(ys, "_resolve_channel_identity", lambda c: ("UCARY","ARY Digital","https://youtube/ary"))
    monkeypatch.setattr(ys, "_channel_video_entries", lambda c, limit=None: (
        "ARY Digital",
        [
            {"id":"arynew1","title":"Zanjerein Episode 20","channel":"ARY Digital"},
            {"id":"aryold1","title":"Zanjerein Episode 19","channel":"ARY Digital"},
        ],
    ))
    monkeypatch.setattr(ys, "_enrich_video_entries", lambda entries, limit=10: [
        ({"id":"arynew1","title":"Zanjerein Episode 20","webpage_url":"https://www.youtube.com/watch?v=arynew1","channel":"ARY Digital","channel_id":"UCARY","timestamp":3000},
         ys.YouTubeVideo("arynew1","Zanjerein Episode 20","https://www.youtube.com/watch?v=arynew1","ARY Digital"),3000),
        ({"id":"aryold1","title":"Zanjerein Episode 19","webpage_url":"https://www.youtube.com/watch?v=aryold1","channel":"ARY Digital","channel_id":"UCARY","timestamp":1000},
         ys.YouTubeVideo("aryold1","Zanjerein Episode 19","https://www.youtube.com/watch?v=aryold1","ARY Digital"),1000),
    ])
    result = ys.latest_matching_video("Zanjerein", channel="ARY Digital")
    assert result.video_id == "arynew1"
    assert result.channel == "ARY Digital"


def test_youtube_planner_advertises_latest_matching_action():
    root=Path(__file__).resolve().parents[1]
    src=(root/"conduit"/"conversation"/"youtube_planner.py").read_text(encoding="utf-8")
    assert '"youtube.play_latest_matching"' in src
    assert "NEWEST relevant video/episode" in src


def test_project_version_is_2059():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")


def test_fallback_routes_latest_episode_with_optional_channel():
    from conduit.conversation.session import ConversationSession
    p1 = ConversationSession._fallback_youtube_plan(
        "open youtube and play the latest episode of drama serial zanjerein"
    )
    assert p1.action == "youtube.play_latest_matching"
    assert "zanjerein" in p1.arguments["query"].casefold()
    assert not p1.arguments.get("channel")

    p2 = ConversationSession._fallback_youtube_plan(
        "open youtube and play the latest episode of drama serial zanjerein from channel ARY Digital"
    )
    assert p2.action == "youtube.play_latest_matching"
    assert p2.arguments["channel"] == "ARY Digital"
    assert "ary digit" not in p2.arguments["query"].casefold()
    assert "zanjerein" in p2.arguments["query"].casefold()
