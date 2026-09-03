"""Models returned by the desktop controller."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class ScreenBounds:
    width: int
    height: int
    left: int = 0
    top: int = 0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains(self, point: Point) -> bool:
        return (
            self.left <= point.x < self.right
            and self.top <= point.y < self.bottom
        )


@dataclass(frozen=True, slots=True)
class DesktopActionResult:
    success: bool
    action: str
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None
