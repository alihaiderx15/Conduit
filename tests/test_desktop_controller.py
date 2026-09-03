from __future__ import annotations

import pytest

from conduit.desktop import DesktopController, Point, ScreenBounds
from conduit.desktop.errors import CoordinateOutOfBoundsError, UnsupportedInputError


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
    def screen_bounds(self) -> ScreenBounds: return ScreenBounds(1920, 1080)
    def mouse_position(self) -> Point: return Point(100, 200)
    def move_to(self, x: int, y: int, duration: float) -> None: self.calls.append(("move", x, y, duration))
    def click(self, x: int, y: int, clicks: int, interval: float, button: str) -> None: self.calls.append(("click", x, y, clicks, interval, button))
    def write(self, text: str, interval: float) -> None: self.calls.append(("write", text, interval))
    def press(self, key: str, presses: int, interval: float) -> None: self.calls.append(("press", key, presses, interval))
    def hotkey(self, *keys: str) -> None: self.calls.append(("hotkey", *keys))
    def scroll(self, amount: int) -> None: self.calls.append(("scroll", amount))


def test_reports_screen_and_pointer() -> None:
    controller = DesktopController(FakeBackend())
    assert controller.screen_bounds() == ScreenBounds(1920, 1080)
    assert controller.mouse_position() == Point(100, 200)


def test_rejects_out_of_bounds_coordinates() -> None:
    controller = DesktopController(FakeBackend())
    with pytest.raises(CoordinateOutOfBoundsError):
        controller.click(1920, 200)


def test_move_and_click_call_backend() -> None:
    backend = FakeBackend(); controller = DesktopController(backend)
    controller.move_mouse(50, 60, 0.5)
    controller.click(70, 80, button="right", clicks=2)
    assert backend.calls[0] == ("move", 50, 60, 0.5)
    assert backend.calls[1][0:4] == ("click", 70, 80, 2)


def test_keyboard_and_scroll_actions() -> None:
    backend = FakeBackend(); controller = DesktopController(backend)
    controller.type_text("hello")
    controller.press_key("enter", 2)
    controller.hotkey(["ctrl", "l"])
    controller.scroll(-5)
    assert [call[0] for call in backend.calls] == ["write", "press", "hotkey", "scroll"]


def test_rejects_unknown_button_or_key() -> None:
    controller = DesktopController(FakeBackend())
    with pytest.raises(UnsupportedInputError): controller.click(1, 1, button="side")
    with pytest.raises(UnsupportedInputError): controller.press_key("definitely-not-a-key")
