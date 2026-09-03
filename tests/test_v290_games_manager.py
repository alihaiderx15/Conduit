
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from conduit.games import GamesService, DownloadState, GamePlatform, InstalledGame
from conduit.conversation.session import ConversationSession


def steam_manifest(path: Path, *, appid="1172470", name="Apex Legends", state=4,
                   downloaded=0, total=0):
    path.write_text(
        '"AppState"\n{\n'
        f'    "appid" "{appid}"\n'
        f'    "name" "{name}"\n'
        '    "installdir" "Apex Legends"\n'
        f'    "StateFlags" "{state}"\n'
        f'    "BytesDownloaded" "{downloaded}"\n'
        f'    "BytesToDownload" "{total}"\n'
        '}\n',
        encoding="utf-8",
    )


def make_steam_library(tmp_path: Path, *, state=4, downloaded=0, total=0):
    steamapps = tmp_path/"steamapps"
    (steamapps/"common"/"Apex Legends").mkdir(parents=True)
    manifest = steamapps/"appmanifest_1172470.acf"
    steam_manifest(manifest, state=state, downloaded=downloaded, total=total)
    return manifest


def test_list_installed_steam_games_from_manifest(tmp_path, monkeypatch):
    make_steam_library(tmp_path)
    service = GamesService()
    monkeypatch.setattr(service, "_steam_libraries", lambda: [tmp_path])
    monkeypatch.setattr(service, "_list_epic", lambda: [])
    games = service.list_installed()
    assert len(games) == 1
    assert games[0].name == "Apex Legends"
    assert games[0].platform is GamePlatform.STEAM
    assert games[0].game_id == "1172470"


def test_no_update_available_is_reported_and_does_not_open_uri(tmp_path, monkeypatch):
    make_steam_library(tmp_path, state=4)
    service = GamesService()
    monkeypatch.setattr(service, "_steam_libraries", lambda: [tmp_path])
    monkeypatch.setattr(service, "_list_epic", lambda: [])
    opened = []
    monkeypatch.setattr(service, "_open_uri", lambda uri: opened.append(uri))
    game = service.find_game("apex legends")
    message, status = service.update(game)
    assert message == "No update available for Apex Legends."
    assert status.state is DownloadState.COMPLETE
    assert status.update_available is False
    assert opened == []


def test_steam_update_required_opens_steam_downloads(tmp_path, monkeypatch):
    # Fully installed + update required.
    make_steam_library(tmp_path, state=4 | 2)
    service = GamesService()
    monkeypatch.setattr(service, "_steam_libraries", lambda: [tmp_path])
    monkeypatch.setattr(service, "_list_epic", lambda: [])
    launched = []
    monkeypatch.setattr(service, "_launch_steam_url", lambda uri: launched.append(uri))
    game = service.find_game("apex")
    message, status = service.update(game)
    assert message == "Requested Steam to update Apex Legends."
    assert status.update_available is True
    assert launched == ["steam://update/1172470"]


def test_download_progress(tmp_path, monkeypatch):
    make_steam_library(
        tmp_path,
        state=4 | 1048576,
        downloaded=250,
        total=1000,
    )
    service = GamesService()
    monkeypatch.setattr(service, "_steam_libraries", lambda: [tmp_path])
    monkeypatch.setattr(service, "_list_epic", lambda: [])
    game = service.find_game("apex")
    status = service.download_status(game)
    assert status.state is DownloadState.DOWNLOADING
    assert status.progress == 25.0


def test_shutdown_intent_only_when_user_explicitly_requests_completion_shutdown():
    session = object.__new__(ConversationSession)
    assert not session._games_shutdown_after_completion("update apex legends")
    assert session._games_shutdown_after_completion(
        "update apex legends and shut down the PC when it finishes"
    )
    assert session._games_shutdown_after_completion(
        "update apex legends then shutdown once the download is complete"
    )


def test_game_name_parser_handles_update_and_schedule():
    session = object.__new__(ConversationSession)
    assert session._games_strip_name("update Apex Legends") == "Apex Legends"
    assert session._games_strip_name(
        "update Apex Legends and shutdown the PC when it finishes"
    ) == "Apex Legends"
    assert session._games_strip_name(
        "schedule Apex Legends update at 23:30"
    ) == "Apex Legends"


def test_game_detector_catches_management_commands(monkeypatch):
    session = object.__new__(ConversationSession)
    assert session._could_be_games_request("list installed games")
    assert session._could_be_games_request("update Apex Legends on Steam")
    assert session._could_be_games_request("schedule Apex Legends update at 23:30")


def test_games_tools_registered():
    from conduit.tools.builtin import registry
    names = {item.name for item in registry.all()}
    required = {
        "games.list",
        "games.install",
        "games.update",
        "games.download_status",
        "games.schedule_update",
        "games.cancel_schedule",
        "games.launch",
    }
    assert required <= names


def test_monitor_waits_for_active_transition_before_completion(monkeypatch):
    service = GamesService()
    game = InstalledGame(
        "Apex Legends",
        GamePlatform.STEAM,
        Path("C:/Games/Apex"),
        "1172470",
    )
    states = iter([
        SimpleNamespace(state=DownloadState.DOWNLOADING, update_available=True),
        SimpleNamespace(state=DownloadState.COMPLETE, update_available=False),
    ])
    last = SimpleNamespace(state=DownloadState.COMPLETE, update_available=False)
    monkeypatch.setattr(service, "download_status", lambda game: next(states, last))
    completed = []
    service.monitor_until_complete(
        game,
        on_complete=lambda g: completed.append(g.name),
        poll_seconds=0.01,
        require_active_transition=True,
    )
    deadline = time.time() + 3
    while time.time() < deadline and not completed:
        time.sleep(0.02)
    assert completed == ["Apex Legends"]


def test_version_290():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
