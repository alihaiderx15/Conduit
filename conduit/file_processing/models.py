
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class FileSource(StrEnum):
    FILESYSTEM = "filesystem"
    GUI_DROP = "gui_drop"
    ATTACHMENT = "attachment"
    CLIPBOARD = "clipboard"
    UNKNOWN = "unknown"


class FileKind(StrEnum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    TEXT = "text"
    SPREADSHEET = "spreadsheet"
    JSON = "json"
    XML = "xml"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"
    PRESENTATION = "presentation"
    CODE = "code"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class FileInput:
    path: Path
    original_name: str
    kind: FileKind
    source: FileSource = FileSource.FILESYSTEM
    temporary: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def data(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "original_name": self.original_name,
            "kind": self.kind.value,
            "source": self.source.value,
            "temporary": self.temporary,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class ProcessingResult:
    success: bool
    action: str
    message: str
    input_file: FileInput
    output_path: Path | None = None
    data: dict[str, Any] = field(default_factory=dict)
    semantic_text: str = ""
    semantic_instruction: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "success": self.success,
            "action": self.action,
            "message": self.message,
            "input": self.input_file.data(),
            "output_path": str(self.output_path) if self.output_path else None,
            "data": dict(self.data),
        }
        if self.semantic_text:
            payload["semantic_text"] = self.semantic_text
        if self.semantic_instruction:
            payload["semantic_instruction"] = self.semantic_instruction
        return payload
