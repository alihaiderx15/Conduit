"""Thin PyAutoGUI backend isolated for testing."""
from __future__ import annotations

from typing import Protocol

from .models import Point, ScreenBounds


class DesktopBackend(Protocol):
    def screen_bounds(self) -> ScreenBounds: ...
    def mouse_position(self) -> Point: ...
    def move_to(self, x: int, y: int, duration: float) -> None: ...
    def click(self, x: int, y: int, clicks: int, interval: float, button: str) -> None: ...
    def write(self, text: str, interval: float) -> None: ...
    def press(self, key: str, presses: int, interval: float) -> None: ...
    def hotkey(self, *keys: str) -> None: ...
    def scroll(self, amount: int) -> None: ...


class PyAutoGUIBackend:
    """Real desktop backend using PyAutoGUI with its corner fail-safe enabled."""

    def __init__(self) -> None:
        import pyautogui

        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.08
        self._api = pyautogui

    def screen_bounds(self) -> ScreenBounds:
        # pyautogui.size() reports the primary monitor only. Conduit's screen
        # observer captures ALL monitors, so vision coordinates can legitimately
        # exceed the primary resolution (for example x=3710 on a 2x1920 setup).
        # Use Windows' virtual-screen rectangle so validation and clicks use the
        # same coordinate space as the desktop.
        try:
            import ctypes
            if hasattr(ctypes, "windll"):
                user32 = ctypes.windll.user32
                left = int(user32.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
                top = int(user32.GetSystemMetrics(77))    # SM_YVIRTUALSCREEN
                width = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
                height = int(user32.GetSystemMetrics(79)) # SM_CYVIRTUALSCREEN
                if width > 0 and height > 0:
                    return ScreenBounds(
                        width=width,
                        height=height,
                        left=left,
                        top=top,
                    )
        except Exception:
            pass

        size = self._api.size()
        return ScreenBounds(width=int(size.width), height=int(size.height))

    def mouse_position(self) -> Point:
        pos = self._api.position()
        return Point(int(pos.x), int(pos.y))

    def move_to(self, x: int, y: int, duration: float) -> None:
        self._api.moveTo(x, y, duration=duration)

    def click(self, x: int, y: int, clicks: int, interval: float, button: str) -> None:
        self._api.click(x=x, y=y, clicks=clicks, interval=interval, button=button)

    def write(self, text: str, interval: float) -> None:
        self._api.write(text, interval=interval)

    def press(self, key: str, presses: int, interval: float) -> None:
        self._api.press(key, presses=presses, interval=interval)

    def hotkey(self, *keys: str) -> None:
        self._api.hotkey(*keys)

    def scroll(self, amount: int) -> None:
        self._api.scroll(amount)
