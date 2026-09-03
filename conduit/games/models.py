
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import StrEnum
from pathlib import Path
from typing import Any


class GamePlatform(StrEnum):
    STEAM = "steam"
    EPIC = "epic"


class DownloadState(StrEnum):
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"
    UPDATE_AVAILABLE = "update_available"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class InstalledGame:
    name: str
    platform: GamePlatform
    install_path: Path
    game_id: str
    manifest_path: Path | None = None
    launch_id: str = ""
    metadata: dict[str, Any] | None = None

    def data(self) -> dict[str, Any]:
        row = asdict(self)
        row["platform"] = self.platform.value
        row["install_path"] = str(self.install_path)
        row["manifest_path"] = str(self.manifest_path) if self.manifest_path else ""
        return row


@dataclass(slots=True)
class DownloadStatus:
    game: InstalledGame
    state: DownloadState
    progress: float | None = None
    bytes_downloaded: int | None = None
    bytes_total: int | None = None
    message: str = ""
    update_available: bool | None = None

    def data(self) -> dict[str, Any]:
        return {
            "game": self.game.data(),
            "state": self.state.value,
            "progress": self.progress,
            "bytes_downloaded": self.bytes_downloaded,
            "bytes_total": self.bytes_total,
            "message": self.message,
            "update_available": self.update_available,
        }
