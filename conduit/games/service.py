
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from typing import Callable

from .models import DownloadState, DownloadStatus, GamePlatform, InstalledGame


class GamesError(RuntimeError):
    pass


# Steam AppState flags used by the desktop client.
STEAM_UPDATE_REQUIRED = 2
STEAM_FULLY_INSTALLED = 4
STEAM_UPDATE_QUEUED = 8
STEAM_FILES_MISSING = 32
STEAM_UPDATE_RUNNING = 256
STEAM_UPDATE_PAUSED = 512
STEAM_UPDATE_STARTED = 1024
STEAM_RECONFIGURING = 65536
STEAM_VALIDATING = 131072
STEAM_PREALLOCATING = 524288
STEAM_DOWNLOADING = 1048576
STEAM_STAGING = 2097152
STEAM_COMMITTING = 4194304


def _parse_vdf_pairs(text: str) -> dict[str, str]:
    # Sufficient for Steam's appmanifest/libraryfolders key/value entries.
    result: dict[str, str] = {}
    for key, value in re.findall(r'"([^"]+)"\s*"([^"]*)"', text):
        result[key] = value
    return result


class GamesService:
    """Local Steam/Epic management backend.

    Discovery and status inspection are based on launcher-owned local manifests.
    Steam install/update/launch uses Steam's URI protocol. Epic launch uses the
    Epic launcher protocol; install/update opens the launcher because Epic does
    not expose a stable public unattended update API.

    No screen coordinates are hard-coded.
    """

    def __init__(self) -> None:
        self._last_game: InstalledGame | None = None
        self._monitors: dict[str, threading.Thread] = {}
        self._monitor_stop: dict[str, threading.Event] = {}

    # ---------- launcher discovery ----------

    @staticmethod
    def _steam_roots() -> list[Path]:
        candidates: list[Path] = []
        env = os.environ
        for raw in (
            env.get("PROGRAMFILES(X86)", "") + r"\Steam",
            env.get("PROGRAMFILES", "") + r"\Steam",
            r"C:\Program Files (x86)\Steam",
            r"C:\Program Files\Steam",
        ):
            if raw:
                p = Path(raw)
                if p.exists():
                    candidates.append(p.resolve())

        # Registry provides the most reliable custom install location on Windows.
        if os.name == "nt":
            try:
                import winreg
                for hive, subkey in (
                    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
                ):
                    try:
                        with winreg.OpenKey(hive, subkey) as key:
                            for value_name in ("SteamPath", "InstallPath"):
                                try:
                                    value, _ = winreg.QueryValueEx(key, value_name)
                                    p = Path(str(value).replace("/", "\\"))
                                    if p.exists():
                                        candidates.append(p.resolve())
                                except OSError:
                                    pass
                    except OSError:
                        pass
            except Exception:
                pass

        unique: list[Path] = []
        seen: set[str] = set()
        for p in candidates:
            key = str(p).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    @classmethod
    def _steam_libraries(cls) -> list[Path]:
        libs: list[Path] = []
        for steam in cls._steam_roots():
            libs.append(steam)
            vdf = steam/"steamapps"/"libraryfolders.vdf"
            if not vdf.exists():
                continue
            text = vdf.read_text(encoding="utf-8", errors="replace")
            # Modern libraryfolders.vdf stores each library under a "path" key.
            for value in re.findall(r'"path"\s*"([^"]+)"', text, flags=re.I):
                p = Path(value.replace(r"\\", "\\"))
                if p.exists():
                    libs.append(p.resolve())
        unique: list[Path] = []
        seen: set[str] = set()
        for p in libs:
            key = str(p).casefold()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    @staticmethod
    def _epic_manifest_dirs() -> list[Path]:
        candidates = [
            Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            /"Epic"/"EpicGamesLauncher"/"Data"/"Manifests",
        ]
        return [p for p in candidates if p.exists()]

    # ---------- installed games ----------

    def list_installed(self) -> list[InstalledGame]:
        games = self._list_steam() + self._list_epic()
        games.sort(key=lambda g: (g.name.casefold(), g.platform.value))
        return games

    def _list_steam(self) -> list[InstalledGame]:
        rows: list[InstalledGame] = []
        seen: set[str] = set()
        for library in self._steam_libraries():
            steamapps = library/"steamapps"
            if not steamapps.exists():
                continue
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    data = _parse_vdf_pairs(
                        manifest.read_text(encoding="utf-8", errors="replace")
                    )
                    appid = str(data.get("appid") or manifest.stem.split("_")[-1])
                    name = str(data.get("name") or f"Steam App {appid}")
                    install_dir = str(data.get("installdir") or "")
                    path = steamapps/"common"/install_dir
                    if not install_dir:
                        continue
                    key = f"steam:{appid}"
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append(InstalledGame(
                        name=name,
                        platform=GamePlatform.STEAM,
                        install_path=path.resolve() if path.exists() else path,
                        game_id=appid,
                        manifest_path=manifest.resolve(),
                        launch_id=appid,
                        metadata={"library": str(library)},
                    ))
                except Exception:
                    continue
        return rows

    def _list_epic(self) -> list[InstalledGame]:
        rows: list[InstalledGame] = []
        seen: set[str] = set()
        for folder in self._epic_manifest_dirs():
            for manifest in folder.glob("*.item"):
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
                    name = str(
                        data.get("DisplayName")
                        or data.get("AppName")
                        or data.get("CatalogItemId")
                        or manifest.stem
                    )
                    install = Path(str(data.get("InstallLocation") or ""))
                    if not str(install):
                        continue
                    app_name = str(data.get("AppName") or "")
                    catalog = str(data.get("CatalogItemId") or "")
                    namespace = str(data.get("CatalogNamespace") or data.get("Namespace") or "")
                    game_id = app_name or catalog or manifest.stem
                    key = f"epic:{game_id}".casefold()
                    if key in seen:
                        continue
                    seen.add(key)
                    launch_id = ":".join(x for x in (namespace, catalog, app_name) if x)
                    rows.append(InstalledGame(
                        name=name,
                        platform=GamePlatform.EPIC,
                        install_path=install,
                        game_id=game_id,
                        manifest_path=manifest.resolve(),
                        launch_id=launch_id,
                        metadata=data,
                    ))
                except Exception:
                    continue
        return rows

    @staticmethod
    def _score_name(query: str, name: str) -> int:
        q = re.sub(r"[^a-z0-9]+", " ", query.casefold()).strip()
        n = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
        if not q or not n:
            return 0
        if q == n:
            return 100
        if q in n or n in q:
            return 80
        q_words = set(q.split())
        n_words = set(n.split())
        common = len(q_words & n_words)
        return common * 15

    def find_game(self, query: str, *, platform: str = "") -> InstalledGame:
        rows = self.list_installed()
        if platform:
            p = platform.casefold().strip()
            rows = [g for g in rows if g.platform.value == p]
        if not rows:
            raise GamesError(
                "I couldn't find any installed games"
                + (f" on {platform.title()}" if platform else "")
                + "."
            )
        ranked = sorted(
            ((self._score_name(query, g.name), g) for g in rows),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < 15:
            raise GamesError(f"I couldn't find an installed game matching '{query}'.")
        self._last_game = ranked[0][1]
        return ranked[0][1]

    def last_game(self) -> InstalledGame | None:
        return self._last_game

    # ---------- status ----------

    def download_status(self, game: InstalledGame) -> DownloadStatus:
        self._last_game = game
        if game.platform is GamePlatform.STEAM:
            return self._steam_status(game)
        return self._epic_status(game)

    def _steam_status(self, game: InstalledGame) -> DownloadStatus:
        manifest = game.manifest_path
        if not manifest or not manifest.exists():
            return DownloadStatus(
                game, DownloadState.UNKNOWN,
                message="Steam manifest is unavailable.",
                update_available=None,
            )
        data = _parse_vdf_pairs(manifest.read_text(encoding="utf-8", errors="replace"))
        try:
            flags = int(data.get("StateFlags", data.get("stateflags", "0")) or 0)
        except ValueError:
            flags = 0

        def integer(*names: str) -> int:
            for name in names:
                raw = data.get(name)
                if raw is not None:
                    try:
                        return int(raw)
                    except ValueError:
                        pass
            return 0

        downloaded = integer("BytesDownloaded", "bytesdownloaded")
        total = integer("BytesToDownload", "bytestodownload")
        progress = None
        if total > 0:
            progress = max(0.0, min(100.0, downloaded * 100.0 / total))

        if flags & STEAM_UPDATE_PAUSED:
            state = DownloadState.PAUSED
        elif flags & (STEAM_DOWNLOADING | STEAM_UPDATE_RUNNING | STEAM_UPDATE_STARTED):
            state = DownloadState.DOWNLOADING
        elif flags & STEAM_UPDATE_QUEUED:
            state = DownloadState.QUEUED
        elif flags & (STEAM_PREALLOCATING | STEAM_STAGING | STEAM_COMMITTING):
            state = DownloadState.INSTALLING
        elif flags & (STEAM_VALIDATING | STEAM_RECONFIGURING):
            state = DownloadState.VERIFYING
        elif flags & (STEAM_UPDATE_REQUIRED | STEAM_FILES_MISSING):
            state = DownloadState.UPDATE_AVAILABLE
        elif flags & STEAM_FULLY_INSTALLED:
            state = DownloadState.COMPLETE
        else:
            state = DownloadState.UNKNOWN

        update_available = bool(
            flags & (
                STEAM_UPDATE_REQUIRED | STEAM_UPDATE_QUEUED | STEAM_UPDATE_RUNNING
                | STEAM_UPDATE_PAUSED | STEAM_UPDATE_STARTED | STEAM_DOWNLOADING
                | STEAM_PREALLOCATING | STEAM_STAGING | STEAM_COMMITTING
            )
        )
        message = {
            DownloadState.COMPLETE: "No update available.",
            DownloadState.UPDATE_AVAILABLE: "An update is available.",
            DownloadState.QUEUED: "Update is queued.",
            DownloadState.DOWNLOADING: "Update is downloading.",
            DownloadState.PAUSED: "Update is paused.",
            DownloadState.INSTALLING: "Update is being installed.",
            DownloadState.VERIFYING: "Steam is verifying the game.",
        }.get(state, "Steam download state is unknown.")
        return DownloadStatus(
            game=game,
            state=state,
            progress=progress,
            bytes_downloaded=downloaded or None,
            bytes_total=total or None,
            message=message,
            update_available=update_available,
        )

    def _epic_status(self, game: InstalledGame) -> DownloadStatus:
        manifest = game.manifest_path
        if not manifest or not manifest.exists():
            return DownloadStatus(
                game, DownloadState.UNKNOWN,
                message="Epic manifest is unavailable.",
                update_available=None,
            )
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            data = {}
        incomplete = bool(data.get("bIsIncompleteInstall", False))
        if incomplete:
            return DownloadStatus(
                game, DownloadState.INSTALLING,
                message="Epic reports that installation/update work is incomplete.",
                update_available=True,
            )
        # Epic's local .item manifest does not expose authoritative remote update
        # availability. Do not falsely claim an update exists.
        return DownloadStatus(
            game,
            DownloadState.COMPLETE,
            message="No update is currently indicated by Epic's local manifest.",
            update_available=False,
        )

    # ---------- launcher actions ----------

    @classmethod
    def _launch_steam_url(cls, uri: str) -> None:
        """Send a Steam protocol URL directly to steam.exe when available."""
        if os.name == "nt":
            for steam_root in cls._steam_roots():
                exe = steam_root/"steam.exe"
                if exe.exists():
                    subprocess.Popen(
                        [str(exe), uri],
                        shell=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
        cls._open_uri(uri)

    @staticmethod
    def _open_uri(uri: str) -> None:
        if os.name != "nt":
            raise GamesError("Launcher URI control is currently implemented for Windows.")
        os.startfile(uri)  # type: ignore[attr-defined]

    def launch(self, game: InstalledGame) -> str:
        self._last_game = game
        if game.platform is GamePlatform.STEAM:
            self._open_uri(f"steam://rungameid/{game.game_id}")
            return f"Launching {game.name} through Steam."
        if game.launch_id:
            encoded = game.launch_id.replace(":", "%3A")
            self._open_uri(
                f"com.epicgames.launcher://apps/{encoded}?action=launch&silent=true"
            )
        else:
            self._open_uri("com.epicgames.launcher://store")
        return f"Launching {game.name} through Epic Games Launcher."

    def install(self, query_or_id: str, *, platform: str = "steam") -> str:
        p = platform.casefold().strip()
        if p == "steam":
            if query_or_id.isdigit():
                self._open_uri(f"steam://install/{query_or_id}")
                return f"Opened Steam installation for app {query_or_id}."
            self._open_uri(
                "steam://store/search/?term=" + query_or_id.replace(" ", "%20")
            )
            return (
                f"Opened Steam search for {query_or_id}. "
                "Select the game in Steam to install it."
            )
        if p == "epic":
            self._open_uri("com.epicgames.launcher://store")
            return (
                f"Opened Epic Games Launcher for {query_or_id}. "
                "Epic does not expose a stable unattended public install API, "
                "so installation must be confirmed in the launcher."
            )
        raise GamesError("Game platform must be Steam or Epic.")

    def update(self, game: InstalledGame) -> tuple[str, DownloadStatus]:
        status = self.download_status(game)

        # Critical UX rule: if local launcher state says fully up-to-date, don't
        # launch an unnecessary update workflow.
        if status.update_available is False and status.state is DownloadState.COMPLETE:
            return f"No update available for {game.name}.", status

        if game.platform is GamePlatform.STEAM:
            if status.state in {
                DownloadState.DOWNLOADING,
                DownloadState.QUEUED,
                DownloadState.INSTALLING,
                DownloadState.VERIFYING,
                DownloadState.PAUSED,
            }:
                return f"{game.name} is already updating.", status

            # Mark's updater uses Steam's dedicated update URI for installed
            # games with pending updates. This is much more direct than
            # attempting to click the Scheduled-row icon in Steam's UI.
            self._launch_steam_url(f"steam://update/{game.game_id}")
            return f"Requested Steam to update {game.name}.", status

        # Epic update state is launcher-managed. Opening the app entry causes the
        # launcher to reconcile/update before launch when an update is required.
        if game.launch_id:
            encoded = game.launch_id.replace(":", "%3A")
            self._open_uri(
                f"com.epicgames.launcher://apps/{encoded}?action=launch&silent=false"
            )
        else:
            self._open_uri("com.epicgames.launcher://library")
        return f"Opened Epic Games Launcher to update {game.name}.", status

    # ---------- scheduled updates ----------

    @staticmethod
    def _schedule_task_name(game: InstalledGame) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]+", "-", game.name).strip("-")[:50] or game.game_id
        return f"Conduit-GameUpdate-{game.platform.value}-{safe}"

    def schedule_update(self, game: InstalledGame, *, when: str) -> str:
        """Schedule a one-time Windows task using HH:MM or YYYY-MM-DD HH:MM.

        The task invokes the installed Conduit Python module with explicit argv;
        no generated shell command is used.
        """
        if os.name != "nt":
            raise GamesError("Scheduled game updates are currently implemented for Windows.")

        raw = str(when or "").strip()
        from datetime import datetime, timedelta

        now = datetime.now()
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt)
                if fmt == "%H:%M":
                    parsed = now.replace(
                        hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0
                    )
                    if parsed <= now:
                        parsed += timedelta(days=1)
                break
            except ValueError:
                continue
        if parsed is None:
            raise GamesError(
                "Schedule time must be HH:MM or YYYY-MM-DD HH:MM, for example '23:30' "
                "or '2026-08-23 02:00'."
            )

        task_name = self._schedule_task_name(game)
        python = sys.executable
        # schtasks /TR takes one command string; every user-derived value is
        # validated/quoted as data, not concatenated into a shell execution.
        game_arg = game.name.replace('"', "")
        platform_arg = game.platform.value
        task_command = (
            f'"{python}" -m conduit.games.scheduled update '
            f'--game "{game_arg}" --platform "{platform_arg}"'
        )
        args = [
            "schtasks", "/Create", "/F",
            "/TN", task_name,
            "/SC", "ONCE",
            "/SD", parsed.strftime("%m/%d/%Y"),
            "/ST", parsed.strftime("%H:%M"),
            "/TR", task_command,
        ]
        result = subprocess.run(
            args, shell=False, capture_output=True, text=True, errors="replace"
        )
        if result.returncode != 0:
            raise GamesError(
                "Windows could not schedule the game update: "
                + (result.stderr or result.stdout).strip()
            )
        self._last_game = game
        return (
            f"Scheduled {game.name} update for {parsed.strftime('%Y-%m-%d %H:%M')}."
        )

    def cancel_schedule(self, game: InstalledGame) -> str:
        if os.name != "nt":
            raise GamesError("Scheduled game updates are currently implemented for Windows.")
        task_name = self._schedule_task_name(game)
        result = subprocess.run(
            ["schtasks", "/Delete", "/F", "/TN", task_name],
            shell=False, capture_output=True, text=True, errors="replace",
        )
        if result.returncode != 0:
            raise GamesError(
                f"I couldn't find an active scheduled update for {game.name}."
            )
        self._last_game = game
        return f"Cancelled the scheduled update for {game.name}."

    # ---------- Steam native update activation ----------

    @staticmethod
    def _uia_control_text(control) -> str:
        parts = []
        try:
            text = control.window_text()
            if text:
                parts.append(str(text))
        except Exception:
            pass
        try:
            info = control.element_info
            for attr in ("name", "automation_id", "control_type"):
                value = getattr(info, attr, "")
                if value:
                    parts.append(str(value))
        except Exception:
            pass
        return " ".join(parts).strip()

    def activate_steam_update_uia(self, game: InstalledGame) -> tuple[bool, str]:
        """Activate the exact game's Download/Update control via Windows UIA."""
        if os.name != "nt":
            return False, "Steam UI activation is only available on Windows."

        try:
            from pywinauto import Desktop
        except Exception as exc:
            return False, f"pywinauto is unavailable: {exc}"

        try:
            self._launch_steam_url("steam://open/downloads")
        except Exception:
            pass
        time.sleep(1.5)

        try:
            ui = Desktop(backend="uia")
            windows = []
            for win in ui.windows():
                try:
                    title = (win.window_text() or "").casefold()
                    process_name = ""
                    try:
                        import psutil
                        process_name = psutil.Process(win.process_id()).name().casefold()
                    except Exception:
                        pass
                    if "steam" not in title and process_name not in {"steam.exe", "steamwebhelper.exe"}:
                        continue
                    rect = win.rectangle()
                    if rect.width() > 400 and rect.height() > 300:
                        windows.append(win)
                except Exception:
                    continue

            if not windows:
                return False, "Steam window was not found through Windows UI Automation."

            windows.sort(
                key=lambda w: w.rectangle().width() * w.rectangle().height(),
                reverse=True,
            )
            win = windows[0]
            try:
                win.set_focus()
            except Exception:
                pass
            time.sleep(0.5)

            controls = list(win.descendants())
            wanted = game.name.casefold()

            row_matches = []
            for ctrl in controls:
                try:
                    text = self._uia_control_text(ctrl).casefold()
                    if wanted not in text:
                        continue
                    rect = ctrl.rectangle()
                    if rect.width() > 0 and rect.height() > 0:
                        row_matches.append((ctrl, rect))
                except Exception:
                    continue

            if not row_matches:
                return False, f"Steam Downloads did not expose the {game.name} row through UI Automation."

            row_matches.sort(key=lambda item: item[1].left)
            _row_control, row_rect = row_matches[0]
            row_y = (row_rect.top + row_rect.bottom) // 2

            named = []
            unnamed = []
            for ctrl in controls:
                try:
                    rect = ctrl.rectangle()
                    if rect.width() <= 0 or rect.height() <= 0:
                        continue

                    center_y = (rect.top + rect.bottom) // 2
                    if abs(center_y - row_y) > max(60, row_rect.height() * 2):
                        continue
                    if rect.left <= row_rect.right:
                        continue

                    info = ctrl.element_info
                    control_type = str(getattr(info, "control_type", "") or "").casefold()
                    if control_type not in {"button", "hyperlink", "image", "custom"}:
                        continue

                    text = self._uia_control_text(ctrl).casefold()
                    if any(word in text for word in ("download", "update", "resume", "start")):
                        score = 200 - abs(center_y - row_y)
                        if "download" in text:
                            score += 40
                        if "update" in text:
                            score += 30
                        named.append((score, ctrl))
                    elif control_type == "button":
                        # Steam sometimes exposes the down-arrow as an unnamed Button.
                        score = rect.left - row_rect.right - abs(center_y - row_y)
                        unnamed.append((score, ctrl))
                except Exception:
                    continue

            candidates = named or unnamed
            if not candidates:
                return False, f"Steam exposed {game.name}, but not its update control."

            candidates.sort(key=lambda item: item[0], reverse=True)
            target = candidates[0][1]

            try:
                target.invoke()
            except Exception:
                try:
                    target.click_input()
                except Exception as exc:
                    return False, f"Steam update control was found but could not be activated: {exc}"

            return True, f"Activated {game.name}'s Steam update control through Windows UI Automation."
        except Exception as exc:
            return False, f"Steam UI Automation failed: {exc}"

    # ---------- completion monitoring ----------

    def monitor_until_complete(
        self,
        game: InstalledGame,
        *,
        on_complete: Callable[[InstalledGame], None] | None = None,
        poll_seconds: float = 5.0,
        require_active_transition: bool = True,
    ) -> str:
        key = f"{game.platform.value}:{game.game_id}".casefold()
        existing = self._monitors.get(key)
        if existing and existing.is_alive():
            return f"Already monitoring {game.name}."

        stop = threading.Event()
        self._monitor_stop[key] = stop

        def worker() -> None:
            saw_active = False
            try:
                while not stop.wait(max(0.05, poll_seconds)):
                    status = self.download_status(game)
                    active = status.state in {
                        DownloadState.UPDATE_AVAILABLE,
                        DownloadState.QUEUED,
                        DownloadState.DOWNLOADING,
                        DownloadState.PAUSED,
                        DownloadState.INSTALLING,
                        DownloadState.VERIFYING,
                    }
                    saw_active = saw_active or active
                    if (
                        status.state is DownloadState.COMPLETE
                        and status.update_available is False
                        and (saw_active or not require_active_transition)
                    ):
                        if on_complete:
                            on_complete(game)
                        break
            finally:
                self._monitor_stop.pop(key, None)
                self._monitors.pop(key, None)

        thread = threading.Thread(
            target=worker,
            name=f"games-monitor:{game.name}",
            daemon=True,
        )
        self._monitors[key] = thread
        thread.start()
        return f"Monitoring {game.name} until the update completes."

    def cancel_monitor(self, game: InstalledGame) -> bool:
        key = f"{game.platform.value}:{game.game_id}".casefold()
        event = self._monitor_stop.get(key)
        if event:
            event.set()
            return True
        return False


games_service = GamesService()
