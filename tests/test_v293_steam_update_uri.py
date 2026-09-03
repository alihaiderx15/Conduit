
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.games import GamesService, GamePlatform, InstalledGame, DownloadState
from conduit.conversation.session import ConversationSession


def make_game(tmp_path, state=6):
    manifest = tmp_path/"appmanifest_1778820.acf"
    manifest.write_text(
        '"AppState"\n{\n'
        ' "appid" "1778820"\n'
        ' "name" "TEKKEN 8"\n'
        ' "installdir" "TEKKEN 8"\n'
        f' "StateFlags" "{state}"\n'
        '}\n',
        encoding="utf-8",
    )
    return InstalledGame(
        "TEKKEN 8", GamePlatform.STEAM, tmp_path/"TEKKEN 8",
        "1778820", manifest_path=manifest,
    )


def test_pending_update_uses_steam_update_uri(tmp_path, monkeypatch):
    service = GamesService()
    game = make_game(tmp_path, state=6)
    launched = []
    monkeypatch.setattr(service, "_launch_steam_url", lambda uri: launched.append(uri))
    message, status = service.update(game)
    assert launched == ["steam://update/1778820"]
    assert message == "Requested Steam to update TEKKEN 8."
    assert status.update_available is True


def test_active_update_is_not_retriggered(tmp_path, monkeypatch):
    service = GamesService()
    game = make_game(tmp_path, state=4 | 1048576)
    launched = []
    monkeypatch.setattr(service, "_launch_steam_url", lambda uri: launched.append(uri))
    message, status = service.update(game)
    assert launched == []
    assert message == "TEKKEN 8 is already updating."
    assert status.state is DownloadState.DOWNLOADING


@pytest.mark.asyncio
async def test_conversation_waits_for_verified_steam_state(monkeypatch):
    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace()
    session._dev_context = {}
    session._code_context = {}
    session._file_context = {}
    session._messaging_context = {}

    game = InstalledGame(
        "TEKKEN 8", GamePlatform.STEAM, Path("C:/Games/TEKKEN 8"), "1778820"
    )

    from conduit.conversation import session as sm

    monkeypatch.setattr(sm.games_service, "find_game", lambda *a, **k: game)
    monkeypatch.setattr(
        sm.games_service,
        "update",
        lambda g: (
            "Requested Steam to update TEKKEN 8.",
            SimpleNamespace(
                update_available=True,
                state=DownloadState.UPDATE_AVAILABLE,
            ),
        ),
    )

    states = iter([
        SimpleNamespace(
            state=DownloadState.UPDATE_AVAILABLE,
            update_available=True,
            message="An update is available.",
        ),
        SimpleNamespace(
            state=DownloadState.DOWNLOADING,
            update_available=True,
            message="Update is downloading.",
        ),
    ])
    monkeypatch.setattr(sm.games_service, "download_status", lambda g: next(states))

    import asyncio
    async def no_sleep(_): return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    answer, report = await session._execute_games_request("update tekken 8")
    assert report.success is True
    assert "Started the Steam update for TEKKEN 8." in answer
    assert "Update is downloading." in answer


def test_version_293():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
