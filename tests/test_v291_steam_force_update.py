
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.games import GamesService, GamePlatform, InstalledGame, DownloadState
from conduit.conversation.session import ConversationSession
from conduit.observer.models import Rectangle, ScreenElement, StructuredScreenAnalysis, ScreenCapture


def make_game(tmp_path):
    manifest = tmp_path/"appmanifest_1778820.acf"
    manifest.write_text(
        '"AppState"\n{\n'
        ' "appid" "1778820"\n'
        ' "name" "TEKKEN 8"\n'
        ' "installdir" "TEKKEN 8"\n'
        ' "StateFlags" "6"\n'
        '}\n',
        encoding="utf-8",
    )
    return InstalledGame(
        "TEKKEN 8", GamePlatform.STEAM, tmp_path/"TEKKEN 8",
        "1778820", manifest_path=manifest,
    )


def test_service_only_opens_downloads_and_does_not_claim_started(tmp_path, monkeypatch):
    service = GamesService()
    game = make_game(tmp_path)
    launched = []
    monkeypatch.setattr(service, "_launch_steam_url", lambda uri: launched.append(uri))
    message, status = service.update(game)
    assert message == "Requested Steam to update TEKKEN 8."
    assert "Started/queued" not in message
    assert launched == ["steam://update/1778820"]
    assert status.update_available is True


@pytest.mark.asyncio
async def test_visual_activation_clicks_download_button_on_same_row(tmp_path, monkeypatch):
    game = make_game(tmp_path)
    capture = ScreenCapture(
        image_path=tmp_path/"screen.png", width=1434, height=854, captured_at=0.0
    )
    analysis = StructuredScreenAnalysis(
        capture=capture,
        application="Steam",
        summary="Downloads",
        elements=(
            ScreenElement(
                "tekken_title", "TEKKEN 8", "text",
                Rectangle(214, 500, 130, 35), 0.99, text="TEKKEN 8"
            ),
            ScreenElement(
                "tekken_download", "Download now", "button",
                Rectangle(1335, 508, 40, 40), 0.98
            ),
            ScreenElement(
                "brawlhalla_download", "Download now", "button",
                Rectangle(1335, 690, 40, 40), 0.98
            ),
        ),
        provider_id="fake",
        model="fake",
    )

    class Observer:
        async def analyze_structured(self, goal):
            return analysis

    clicks=[]
    class Desktop:
        def capture_point_to_desktop(self, x, y, *, capture_width, capture_height):
            return SimpleNamespace(x=x, y=y)
        def click(self, x, y):
            clicks.append((x,y))

    session=object.__new__(ConversationSession)
    session.agent=SimpleNamespace(
        router=SimpleNamespace(observer=Observer(),desktop=Desktop())
    )

    from conduit.conversation import session as sm
    monkeypatch.setattr(
        sm.games_service,
        "download_status",
        lambda game: SimpleNamespace(
            state=DownloadState.DOWNLOADING,
            update_available=True,
            message="Update is downloading.",
        ),
    )

    import asyncio
    async def no_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio,"sleep",no_sleep)

    ok,message=await session._activate_steam_scheduled_update(game)
    assert ok is True
    assert clicks == [(1355,528)]
    assert "Started the Steam update" in message


@pytest.mark.asyncio
async def test_visual_activation_refuses_without_vision_or_desktop(tmp_path):
    game=make_game(tmp_path)
    session=object.__new__(ConversationSession)
    session.agent=SimpleNamespace(router=SimpleNamespace(observer=None,desktop=None))
    ok,message=await session._activate_steam_scheduled_update(game)
    assert ok is False
    assert "vision-capable" in message


def test_version_291():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
