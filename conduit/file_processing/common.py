
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


class FileProcessingError(RuntimeError):
    pass


class DependencyUnavailable(FileProcessingError):
    pass


def safe_output_path(source: Path, suffix: str, extension: str | None = None) -> Path:
    ext = extension if extension is not None else source.suffix
    if ext and not ext.startswith("."):
        ext = "." + ext
    candidate = source.with_name(f"{source.stem}_{suffix}{ext}")
    n = 2
    while candidate.exists():
        candidate = source.with_name(f"{source.stem}_{suffix}_{n}{ext}")
        n += 1
    return candidate


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileProcessingError(f"File does not exist: {path}")
    if not path.is_file():
        raise FileProcessingError(f"Path is not a file: {path}")


def run_process(command: list[str], *, timeout: float = 120.0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise FileProcessingError(
            result.stderr.strip() or result.stdout.strip() or "External processor failed."
        )
    return result


def ffmpeg_executable(name: str = "ffmpeg") -> str:
    value = shutil.which(name)
    if value:
        return value

    # The normal Conduit install includes imageio-ffmpeg, which ships a usable
    # FFmpeg executable. This makes common conversions such as MP4 -> MP3 work
    # without asking the user to configure a separate FFmpeg PATH first.
    if name.casefold() == "ffmpeg":
        try:
            import imageio_ffmpeg
            bundled = imageio_ffmpeg.get_ffmpeg_exe()
            if bundled and Path(bundled).exists():
                return str(bundled)
        except Exception:
            pass

    raise DependencyUnavailable(
        f"{name} is required for this media action but is not installed or not on PATH."
    )


def file_basic_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "path": str(path),
        "extension": path.suffix.casefold(),
        "size_bytes": stat.st_size,
        "modified_time": stat.st_mtime,
    }


def write_text_output(source: Path, suffix: str, text: str) -> Path:
    target = safe_output_path(source, suffix, ".txt")
    target.write_text(text, encoding="utf-8")
    return target
