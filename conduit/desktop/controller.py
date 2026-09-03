"""Validated, provider-neutral desktop input controller."""
from __future__ import annotations

from collections.abc import Sequence

from conduit.events import EventBus, EventNames

from .backend import DesktopBackend, PyAutoGUIBackend
from .errors import CoordinateOutOfBoundsError, UnsupportedInputError
from .models import DesktopActionResult, Point, ScreenBounds

_ALLOWED_BUTTONS = {"left", "middle", "right"}
_ALLOWED_KEYS = {
    "enter", "tab", "esc", "escape", "space", "backspace", "delete", "home", "end",
    "up", "down", "left", "right", "pageup", "pagedown", "insert", "shift", "ctrl",
    "alt", "win", "command", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8",
    "f9", "f10", "f11", "f12", "volumeup", "volumedown", "volumemute", "playpause",
}


class DesktopController:
    """Execute bounded mouse and keyboard actions through an injectable backend."""

    def __init__(
        self,
        backend: DesktopBackend | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._backend = backend or PyAutoGUIBackend()
        self._events = event_bus

    def _action_started(self, action: str, data: dict[str, object]) -> None:
        if self._events is not None:
            self._events.emit_nowait(
                EventNames.DESKTOP_ACTION_STARTED,
                source="DesktopController",
                payload={"action": action, **data},
            )

    def _action_completed(self, result: DesktopActionResult) -> DesktopActionResult:
        if self._events is not None:
            self._events.emit_nowait(
                EventNames.DESKTOP_ACTION_COMPLETED,
                source="DesktopController",
                payload={
                    "action": result.action,
                    "success": result.success,
                    "message": result.message,
                    "data": dict(result.data),
                },
            )
        return result

    def screen_bounds(self) -> ScreenBounds:
        return self._backend.screen_bounds()

    def mouse_position(self) -> Point:
        return self._backend.mouse_position()

    def _validate_point(self, x: int, y: int) -> Point:
        point = Point(x=x, y=y)
        bounds = self.screen_bounds()
        if not bounds.contains(point):
            raise CoordinateOutOfBoundsError(
                f"Point ({x}, {y}) is outside the screen bounds {bounds.width}x{bounds.height}."
            )
        return point

    def capture_point_to_desktop(
        self,
        x: int,
        y: int,
        *,
        capture_width: int,
        capture_height: int,
    ) -> Point:
        """Translate an all-monitor screenshot point into desktop coordinates.

        Pillow ImageGrab(all_screens=True) uses the virtual desktop's top-left as
        screenshot coordinate (0, 0). Windows input APIs use the actual virtual
        desktop origin, which can be negative when a monitor is left/above the
        primary display.
        """
        x = int(x)
        y = int(y)
        capture_width = int(capture_width)
        capture_height = int(capture_height)
        if not (0 <= x < capture_width and 0 <= y < capture_height):
            raise CoordinateOutOfBoundsError(
                f"Capture point ({x}, {y}) is outside screenshot bounds "
                f"{capture_width}x{capture_height}."
            )

        bounds = self.screen_bounds()
        # If the screenshot spans the virtual desktop (normal Conduit path),
        # offset from image-relative coordinates into Windows coordinates.
        if (
            abs(capture_width - bounds.width) <= 2
            and abs(capture_height - bounds.height) <= 2
        ):
            point = Point(bounds.left + x, bounds.top + y)
        else:
            # Safe fallback for injected/test screenshot backends.
            point = Point(x, y)

        return self._validate_point(point.x, point.y)

    def move_mouse(self, x: int, y: int, duration: float = 0.25) -> DesktopActionResult:
        point = self._validate_point(x, y)
        duration = max(0.0, min(float(duration), 5.0))
        self._action_started("move_mouse", {"x": x, "y": y, "duration": duration})
        self._backend.move_to(point.x, point.y, duration)
        return self._action_completed(DesktopActionResult(True, "move_mouse", f"Moved the pointer to ({x}, {y}).", {"x": x, "y": y}))

    def click(
        self,
        x: int,
        y: int,
        *,
        button: str = "left",
        clicks: int = 1,
        interval: float = 0.12,
    ) -> DesktopActionResult:
        point = self._validate_point(x, y)
        button = button.casefold().strip()
        if button not in _ALLOWED_BUTTONS:
            raise UnsupportedInputError(f"Unsupported mouse button: {button}")
        if not 1 <= clicks <= 3:
            raise ValueError("clicks must be between 1 and 3.")
        interval = max(0.0, min(float(interval), 2.0))
        self._action_started("click", {"x": x, "y": y, "button": button, "clicks": clicks})
        self._backend.click(point.x, point.y, clicks, interval, button)
        label = "Clicked" if clicks == 1 else f"Clicked {clicks} times"
        return self._action_completed(DesktopActionResult(
            True,
            "click",
            f"{label} at ({x}, {y}) using the {button} button.",
            {"x": x, "y": y, "button": button, "clicks": clicks},
        ))

    def type_text(self, text: str, interval: float = 0.03) -> DesktopActionResult:
        if not isinstance(text, str) or not text:
            raise ValueError("text must be a non-empty string.")
        if len(text) > 5000:
            raise ValueError("text is too long for one desktop action.")
        interval = max(0.0, min(float(interval), 1.0))
        self._action_started("type_text", {"length": len(text)})
        self._backend.write(text, interval)
        return self._action_completed(DesktopActionResult(True, "type_text", f"Typed {len(text)} characters.", {"length": len(text)}))

    def press_key(self, key: str, presses: int = 1, interval: float = 0.08) -> DesktopActionResult:
        normalized = key.casefold().strip()
        if len(normalized) == 1 and normalized.isprintable():
            pass
        elif normalized not in _ALLOWED_KEYS:
            raise UnsupportedInputError(f"Unsupported key: {key}")
        if not 1 <= presses <= 20:
            raise ValueError("presses must be between 1 and 20.")
        interval = max(0.0, min(float(interval), 1.0))
        self._action_started("press_key", {"key": normalized, "presses": presses})
        self._backend.press(normalized, presses, interval)
        return self._action_completed(DesktopActionResult(True, "press_key", f"Pressed {normalized} {presses} time(s)."))

    def hotkey(self, keys: Sequence[str]) -> DesktopActionResult:
        normalized = tuple(str(key).casefold().strip() for key in keys)
        if not 2 <= len(normalized) <= 4:
            raise ValueError("A hotkey must contain between 2 and 4 keys.")
        for key in normalized:
            if not ((len(key) == 1 and key.isprintable()) or key in _ALLOWED_KEYS):
                raise UnsupportedInputError(f"Unsupported hotkey key: {key}")
        self._action_started("hotkey", {"keys": normalized})
        self._backend.hotkey(*normalized)
        return self._action_completed(DesktopActionResult(True, "hotkey", f"Pressed {' + '.join(normalized)}.", {"keys": normalized}))

    def scroll(self, amount: int) -> DesktopActionResult:
        if not isinstance(amount, int) or isinstance(amount, bool):
            raise TypeError("amount must be an integer.")
        if amount == 0 or abs(amount) > 100:
            raise ValueError("amount must be between -100 and 100, excluding zero.")
        self._action_started("scroll", {"amount": amount})
        self._backend.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return self._action_completed(DesktopActionResult(True, "scroll", f"Scrolled {direction} by {abs(amount)} step(s).", {"amount": amount}))
