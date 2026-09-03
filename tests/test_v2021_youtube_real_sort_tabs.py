
import conduit.capabilities.youtube_structured as ys


def test_popular_uses_real_youtube_sort_chip(monkeypatch):
    expected = ys.YouTubeVideo(
        video_id="popular123",
        title="Most Popular",
        url="https://www.youtube.com/watch?v=popular123",
        channel="Example",
    )
    calls = []
    monkeypatch.setattr(
        ys,
        "_video_from_channel_sort_chip",
        lambda channel, label: calls.append((channel, label)) or expected,
    )
    assert ys.most_popular_upload("Example") == expected
    assert calls == [("Example", "Popular")]


def test_oldest_prefers_real_oldest_sort_chip(monkeypatch):
    expected = ys.YouTubeVideo(
        video_id="oldest123",
        title="Oldest",
        url="https://www.youtube.com/watch?v=oldest123",
        channel="Example",
    )
    monkeypatch.setattr(
        ys,
        "_video_from_channel_sort_chip",
        lambda channel, label: expected,
    )
    assert ys.oldest_upload("Example") == expected


def test_latest_prefers_real_latest_sort_chip(monkeypatch):
    expected = ys.YouTubeVideo(
        video_id="latest123",
        title="Latest",
        url="https://www.youtube.com/watch?v=latest123",
        channel="Example",
    )
    monkeypatch.setattr(
        ys,
        "_video_from_channel_sort_chip",
        lambda channel, label: expected,
    )
    assert ys.latest_upload("Example") == expected


def test_popular_no_longer_uses_legacy_sort_query():
    source = open(ys.__file__, encoding="utf-8").read()
    block = source[
        source.index("def most_popular_upload"):
        source.index("def play_most_popular_visible")
    ]
    assert "sort=p" not in block
    assert '"Popular"' in block


def test_sort_browser_is_headless():
    source = open(ys.__file__, encoding="utf-8").read()
    block = source[
        source.index("def _video_from_channel_sort_chip"):
        source.index("def latest_upload")
    ]
    assert "launch(headless=True)" in block
    assert '"Latest / Popular /\\n    Oldest"' not in block  # sanity that implementation is executable code
