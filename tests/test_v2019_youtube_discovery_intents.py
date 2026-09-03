
from conduit.conversation.session import ConversationSession
from conduit.conversation.youtube_planner import _ALLOWED


def test_new_youtube_actions_are_allowed():
    assert "youtube.play_oldest_upload" in _ALLOWED
    assert "youtube.play_most_popular" in _ALLOWED
    assert "youtube.play_live" in _ALLOWED


def test_fallback_oldest_popular_live_and_yt_alias():
    old = ConversationSession._fallback_youtube_plan("play the oldest video of Mr Beast")
    assert old.action == "youtube.play_oldest_upload"
    assert old.arguments["channel"] == "Mr Beast"

    popular = ConversationSession._fallback_youtube_plan("play the most popular video from channel aceu")
    assert popular.action == "youtube.play_most_popular"
    assert popular.arguments["channel"] == "aceu"

    live = ConversationSession._fallback_youtube_plan("play the live stream of Mande")
    assert live.action == "youtube.play_live"
    assert live.arguments["channel"] == "Mande"


def test_channel_capabilities_registered():
    from conduit.tools.builtin import registry
    for name in (
        "youtube.play_oldest_upload",
        "youtube.play_most_popular",
        "youtube.play_live",
    ):
        assert registry.get(name).name == name
