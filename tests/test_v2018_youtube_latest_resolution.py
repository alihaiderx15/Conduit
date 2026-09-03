
import conduit.capabilities.youtube_structured as ys


def test_channel_name_normalization_handles_spaces():
    assert ys._norm_channel_name("Mr Beast") == "mrbeast"
    assert ys._norm_channel_name("@MrBeast") == "mrbeast"


def test_latest_logic_does_not_construct_handle_from_display_name():
    # Regression contract: human names must go through channel resolution.
    source = (ys.__file__ and open(ys.__file__, encoding="utf-8").read())
    latest = source[source.index("def latest_upload("):source.index("def play_latest_upload_visible")]
    assert 'handle = value if value.startswith("@")' not in latest
    assert '_resolve_channel_identity(channel)' in latest
    assert 'channel/{channel_id}/videos' in latest


def test_latest_normal_video_prefers_videos_tab_before_rss():
    source = open(ys.__file__, encoding="utf-8").read()
    latest = source[source.index("def latest_upload("):source.index("def play_latest_upload_visible")]
    assert latest.index('channel/{channel_id}/videos') < latest.index("_latest_from_rss(channel_id)")
