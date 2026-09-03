from conduit.capabilities.youtube import YouTubeAgent


def test_normalize_youtube_handle():
    assert YouTubeAgent._normalize_handle("aceu") == "@aceu"
    assert YouTubeAgent._normalize_handle("@aceu") == "@aceu"
    assert YouTubeAgent._normalize_handle("https://www.youtube.com/@aceu/") == "@aceu"


def test_watch_url_validation_and_video_id():
    assert YouTubeAgent._is_watch_url("/watch?v=abc123") is True
    assert YouTubeAgent._is_watch_url("https://www.youtube.com/watch?v=xyz789&list=test") is True
    assert YouTubeAgent._is_watch_url("/shorts/abc123") is False
    assert YouTubeAgent._is_watch_url("/playlist?list=abc") is False
    assert YouTubeAgent._video_id("/watch?v=abc123") == "abc123"


def test_candidate_normalization_preserves_order_and_removes_duplicates():
    result = YouTubeAgent._normalize_candidates(
        [
            {"href": "/watch?v=newest", "title": "Newest video"},
            {"href": "/watch?v=newest&list=uploads", "title": "Duplicate"},
            {"href": "/shorts/short1", "title": "A short"},
            {"href": "https://www.youtube.com/watch?v=older", "title": " Older   video "},
            {"href": "/playlist?list=test", "title": "Playlist"},
        ]
    )

    assert [item.href for item in result] == [
        "/watch?v=newest",
        "https://www.youtube.com/watch?v=older",
    ]
    assert [item.title for item in result] == ["Newest video", "Older video"]
