
from pathlib import Path
from types import SimpleNamespace
import sys

from conduit.capabilities import youtube_structured as ys


def _fake_search_module(monkeypatch, entries):
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, target, download=False):
            assert str(target).startswith("ytsearch")
            return {"entries": entries}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))


def test_hum_tv_scoped_search_picks_full_episode_not_newer_clip(monkeypatch):
    monkeypatch.setattr(ys, "_resolve_channel_identity", lambda c: ("UCHUM", "HUM TV", "url"))
    entries = [{"id":"clip"},{"id":"ep30"},{"id":"other"}]
    _fake_search_module(monkeypatch, entries)

    monkeypatch.setattr(ys, "_enrich_video_entries", lambda entries, limit=10: [
        (
            {"id":"clip","title":"Rabiya Ne Itni Khidmat Ki Ky Pyar Ho Gaya...! #Zanjeerain",
             "channel":"HUM TV","channel_id":"UCHUM","timestamp":9000,"duration":70},
            ys.YouTubeVideo("clip","Rabiya Ne Itni Khidmat Ki Ky Pyar Ho Gaya...! #Zanjeerain","u1","HUM TV",duration=70),
            9000,
        ),
        (
            {"id":"ep30","title":"Zanjeerain Episode 30 [Eng Sub] - 11th Aug 2026 | HUM TV",
             "channel":"HUM TV","channel_id":"UCHUM","timestamp":8000,"duration":2200},
            ys.YouTubeVideo("ep30","Zanjeerain Episode 30 [Eng Sub] - 11th Aug 2026 | HUM TV","u2","HUM TV",duration=2200),
            8000,
        ),
        (
            {"id":"other","title":"Zanjeerain Episode 31","channel":"Other TV","channel_id":"UCOTHER",
             "timestamp":10000,"duration":2200},
            ys.YouTubeVideo("other","Zanjeerain Episode 31","u3","Other TV",duration=2200),
            10000,
        ),
    ])

    result = ys.latest_matching_video("episode of drama serial Zanjeerain", channel="HUM TV")
    assert result.video_id == "ep30"
    assert result.channel == "HUM TV"


def test_channel_search_requires_exact_channel_id(monkeypatch):
    monkeypatch.setattr(ys, "_resolve_channel_identity", lambda c: ("UCARY", "ARY Digital HD", "url"))
    _fake_search_module(monkeypatch, [{"id":"hum"}])
    monkeypatch.setattr(ys, "_enrich_video_entries", lambda entries, limit=10: [
        (
            {"id":"hum","title":"Zanjeerain Episode 30","channel":"HUM TV",
             "channel_id":"UCHUM","timestamp":9000,"duration":2200},
            ys.YouTubeVideo("hum","Zanjeerain Episode 30","u","HUM TV",duration=2200),
            9000,
        ),
    ])
    monkeypatch.setattr(ys, "_channel_video_entries", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("none")))

    try:
        ys.latest_matching_video("episode of drama serial Zanjeerain", channel="ARY Digital")
    except RuntimeError as exc:
        assert "ARY Digital HD" in str(exc)
    else:
        raise AssertionError("Must not accept HUM TV for ARY Digital")


def test_project_version_is_2062():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
