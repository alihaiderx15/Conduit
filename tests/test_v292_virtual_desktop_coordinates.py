
from types import SimpleNamespace
from pathlib import Path

from conduit.desktop.controller import DesktopController
from conduit.desktop.models import ScreenBounds, Point


class FakeBackend:
    def __init__(self, bounds):
        self.bounds = bounds
        self.clicked = []
    def screen_bounds(self):
        return self.bounds
    def mouse_position(self):
        return Point(0, 0)
    def move_to(self, x, y, duration):
        pass
    def click(self, x, y, clicks, interval, button):
        self.clicked.append((x, y))
    def write(self, text, interval):
        pass
    def press(self, key, presses, interval):
        pass
    def hotkey(self, *keys):
        pass
    def scroll(self, amount):
        pass


def test_virtual_bounds_accept_second_monitor_coordinate():
    bounds = ScreenBounds(width=3840, height=1080, left=0, top=0)
    assert bounds.contains(Point(3710, 505))
    assert not bounds.contains(Point(3900, 505))


def test_controller_click_accepts_second_monitor_coordinate():
    backend = FakeBackend(ScreenBounds(width=3840, height=1080))
    controller = DesktopController(backend=backend)
    controller.click(3710, 505)
    assert backend.clicked == [(3710, 505)]


def test_capture_coordinates_translate_negative_virtual_origin():
    backend = FakeBackend(
        ScreenBounds(width=3840, height=1080, left=-1920, top=0)
    )
    controller = DesktopController(backend=backend)
    point = controller.capture_point_to_desktop(
        500, 505, capture_width=3840, capture_height=1080
    )
    assert point == Point(-1420, 505)


def test_capture_coordinates_on_right_monitor_remain_large_positive():
    backend = FakeBackend(
        ScreenBounds(width=3840, height=1080, left=0, top=0)
    )
    controller = DesktopController(backend=backend)
    point = controller.capture_point_to_desktop(
        3710, 505, capture_width=3840, capture_height=1080
    )
    assert point == Point(3710, 505)


def test_version_292():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
