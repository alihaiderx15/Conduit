
from pathlib import Path
from types import SimpleNamespace
import sys
from conduit.capabilities import youtube_structured as ys


def test_hum_tv_clip_cannot_beat_full_episode(monkeypatch):
    monkeypatch.setattr(ys, "_resolve_channel_identity", lambda c: ("UCHUM","HUM TV","url"))
    class FakeYDL:
        def __init__(self, opts): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def extract_info(self, target, download=False):
            return {"entries": [{"id":"clip1"},{"id":"ep30"},{"id":"ep29"}]}
    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYDL))
    monkeypatch.setattr(ys, "_channel_video_entries", lambda c, limit=None: (
        "HUM TV",
        [
            {"id":"clip1","title":"Rabiya Ne Itni Khidmat Ki Ky Pyar Ho Gaya...! #sajalaly #danyalzafar | Zanjeerain"},
            {"id":"ep30","title":"Zanjeerain Episode 30 [Eng Sub] - 9th Aug 2026 | ft. Sajal Aly & Danyal Zafar - HUM TV"},
            {"id":"ep29","title":"Zanjeerain Episode 29 [Eng Sub] - HUM TV"},
        ],
    ))
    monkeypatch.setattr(ys, "_enrich_video_entries", lambda entries, limit=10: [
        (
            {"id":"ep30","title":"Zanjeerain Episode 30 [Eng Sub] - 9th Aug 2026 | ft. Sajal Aly & Danyal Zafar - HUM TV",
             "channel":"HUM TV","channel_id":"UCHUM","timestamp":8000,"duration":2300},
            ys.YouTubeVideo("ep30","Zanjeerain Episode 30 [Eng Sub] - 9th Aug 2026 | ft. Sajal Aly & Danyal Zafar - HUM TV","u2","HUM TV",duration=2300),
            8000,
        ),
        (
            {"id":"ep29","title":"Zanjeerain Episode 29 [Eng Sub] - HUM TV",
             "channel":"HUM TV","channel_id":"UCHUM","timestamp":5000,"duration":2250},
            ys.YouTubeVideo("ep29","Zanjeerain Episode 29 [Eng Sub] - HUM TV","u3","HUM TV",duration=2250),
            5000,
        ),
    ])
    result = ys.latest_matching_video("episode of drama serial Zanjeerain", channel="HUM TV")
    assert result.video_id == "ep30"


def test_numbered_short_clip_is_not_full_episode():
    assert ys._looks_like_full_episode({"title":"Zanjeerain Episode 30","duration":2200})
    assert not ys._looks_like_full_episode({"title":"Zanjeerain Episode 30 Clip","duration":70})


def test_project_version_is_2061():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
