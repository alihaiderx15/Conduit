"""Provider-neutral message and tool-call models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Portable function declaration understood by every provider adapter."""

    name: str
    description: str
    parameters: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


@dataclass(frozen=True, slots=True)
class ToolCall:
    name: str
    arguments: Mapping[str, Any]
    call_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    model: str | None = None
    raw: Any = None

    @property
    def requests_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass(frozen=True, slots=True)
class ImageInput:
    path: Path

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    chat: bool = True
    tools: bool = True
    vision: bool = False
    streaming: bool = False


MessageSequence = Sequence[ChatMessage]
