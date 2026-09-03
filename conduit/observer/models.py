"""Provider-neutral models for structured desktop perception."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class WindowInfo:
    """Metadata about the active desktop window."""

    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


@dataclass(frozen=True, slots=True)
class ScreenCapture:
    """A screenshot and desktop metadata captured with it."""

    image_path: Path
    width: int
    height: int
    captured_at: datetime
    active_window: WindowInfo | None = None

    @classmethod
    def create(
        cls,
        image_path: Path,
        width: int,
        height: int,
        active_window: WindowInfo | None = None,
    ) -> "ScreenCapture":
        return cls(
            image_path=image_path,
            width=width,
            height=height,
            captured_at=datetime.now(timezone.utc),
            active_window=active_window,
        )


@dataclass(frozen=True, slots=True)
class Rectangle:
    """Pixel bounds of a visible screen element."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def is_within(self, screen_width: int, screen_height: int) -> bool:
        return (
            self.x >= 0
            and self.y >= 0
            and self.width > 0
            and self.height > 0
            and self.right <= screen_width
            and self.bottom <= screen_height
        )


@dataclass(frozen=True, slots=True)
class ScreenElement:
    """A structured interactive or informative element visible on screen."""

    element_id: str
    label: str
    role: str
    bounds: Rectangle
    confidence: float
    text: str = ""
    enabled: bool = True
    visible: bool = True

    @property
    def center(self) -> tuple[int, int]:
        return self.bounds.center_x, self.bounds.center_y


@dataclass(frozen=True, slots=True)
class StructuredScreenAnalysis:
    """Structured perception result tied to one screenshot."""

    capture: ScreenCapture
    application: str
    summary: str
    elements: tuple[ScreenElement, ...]
    provider_id: str
    model: str
    raw_text: str = ""

    def interactive_elements(self) -> tuple[ScreenElement, ...]:
        roles = {
            "button", "textbox", "link", "checkbox", "radio", "menuitem",
            "tab", "combobox", "slider", "listitem", "input",
        }
        return tuple(
            element
            for element in self.elements
            if element.visible and element.enabled and element.role.casefold() in roles
        )

    def labels(self) -> tuple[str, ...]:
        return tuple(element.label for element in self.elements)


@dataclass(frozen=True, slots=True)
class ScreenAnalysis:
    """Backward-compatible free-form visual analysis result."""

    capture: ScreenCapture
    prompt: str
    description: str
    provider_id: str
    model: str


@dataclass(frozen=True, slots=True)
class ScreenChange:
    """Comparison of two structured screen states."""

    changed: bool
    application_changed: bool
    added: tuple[str, ...]
    removed: tuple[str, ...]
    summary: str
