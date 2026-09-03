"""Typed browser-engine models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping


class TargetKind(StrEnum):
    ROLE = "role"
    TEXT = "text"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    TEST_ID = "test_id"
    CSS = "css"


@dataclass(frozen=True, slots=True)
class BrowserTarget:
    """Semantic description of one page element."""

    kind: TargetKind
    value: str
    name: str | None = None
    exact: bool = False

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("Browser target value cannot be empty.")


@dataclass(frozen=True, slots=True)
class BrowserState:
    """Small structured snapshot of the active page."""

    title: str
    url: str
    visible_text: str
    viewport_width: int
    viewport_height: int


@dataclass(frozen=True, slots=True)
class BrowserActionResult:
    """Result returned by browser actions."""

    success: bool
    action: str
    message: str
    state: BrowserState | None = None
    data: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DownloadResult:
    """Information about a completed browser download."""

    suggested_filename: str
    saved_path: Path
    url: str
