"""Windows screenshot capture and active-window inspection."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import tempfile
from pathlib import Path
from typing import Protocol

from PIL import ImageGrab

from conduit.events import EventBus, EventNames
from conduit.observer.models import ScreenCapture, WindowInfo


class ScreenshotBackend(Protocol):
    """Contract that allows screenshot capture to be unit tested."""

    def capture(self, destination: Path) -> tuple[int, int]: ...


class PillowScreenshotBackend:
    """Capture all Windows monitors using Pillow's ImageGrab backend."""

    def capture(self, destination: Path) -> tuple[int, int]:
        image = ImageGrab.grab(all_screens=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, format="PNG")
        return image.size


class DesktopCaptureService:
    """Create temporary PNG screenshots and attach active-window metadata."""

    def __init__(
        self,
        backend: ScreenshotBackend | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._backend = backend or PillowScreenshotBackend()
        self._events = event_bus

    def capture(self, destination: Path | None = None) -> ScreenCapture:
        if destination is None:
            directory = Path(tempfile.gettempdir()) / "conduit" / "screenshots"
            directory.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                prefix="screen_", suffix=".png", dir=directory, delete=False
            )
            handle.close()
            destination = Path(handle.name)

        width, height = self._backend.capture(destination)
        capture = ScreenCapture.create(
            image_path=destination,
            width=width,
            height=height,
            active_window=get_active_window(),
        )
        if self._events is not None:
            self._events.emit_nowait(
                EventNames.SCREEN_CAPTURED,
                source="DesktopCaptureService",
                payload={
                    "image_path": str(capture.image_path),
                    "width": capture.width,
                    "height": capture.height,
                    "active_window": capture.active_window.title if capture.active_window else None,
                },
            )
        return capture


def get_active_window() -> WindowInfo | None:
    """Return foreground-window title and bounds on Windows."""

    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return WindowInfo(
        title=buffer.value,
        left=int(rect.left),
        top=int(rect.top),
        right=int(rect.right),
        bottom=int(rect.bottom),
    )
