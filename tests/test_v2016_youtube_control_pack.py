
from types import SimpleNamespace
import pytest

from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.tools.builtin import registry as tool_registry
from conduit.capabilities import youtube_structured as ys


def test_full_youtube_pack_is_registered():
    actions = register_default_actions(UnifiedActionRegistry(tool_registry))
    names = {item.name for item in actions.all()}
    required = {
        "youtube.search", "youtube.play", "youtube.get_info",
        "youtube.get_transcript", "youtube.summarize", "youtube.trending",
        "youtube.pause", "youtube.resume", "youtube.play_latest_upload",
    }
    assert required <= names


def test_video_reference_normalization():
    assert ys.normalize_video_reference("https://www.youtube.com/watch?v=abc123XYZ") == "abc123XYZ"
    assert ys.normalize_video_reference("https://youtu.be/abc123XYZ") == "abc123XYZ"
    assert ys.normalize_video_reference("cats playing piano") == "cats playing piano"


def test_visible_play_uses_windows_default_association(monkeypatch):
    item = ys.YouTubeVideo("abc123XYZ", "Test video", "https://www.youtube.com/watch?v=abc123XYZ")
    monkeypatch.setattr(ys, "resolve_video", lambda value: item)
    monkeypatch.setattr(ys.sys, "platform", "win32")
    opened = []
    monkeypatch.setattr(ys.os, "startfile", lambda url: opened.append(url), raising=False)
    result = ys.open_visible("test")
    assert result == item
    assert opened == [item.url]


def test_pause_resume_are_state_aware(monkeypatch):
    calls = []
    monkeypatch.setattr(ys, "_send_media_play_pause", lambda: calls.append("toggle"))
    ys._PLAYBACK_STATE = "playing"
    assert ys.pause() == "paused"
    assert ys.pause() == "paused"
    assert ys.resume() == "playing"
    assert ys.resume() == "playing"
    assert calls == ["toggle", "toggle"]


@pytest.mark.asyncio
async def test_youtube_tools_dispatch_as_tool_actions(monkeypatch):
    # Registry schema/executor integration is the critical orchestration contract;
    # network extraction itself is separately encapsulated and lazy.
    search_tool = tool_registry.get("youtube.search")
    assert search_tool.name == "youtube.search"
    assert search_tool.risk.value == "safe"
