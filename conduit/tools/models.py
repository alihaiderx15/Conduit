from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Mapping

class ToolRisk(str, Enum):
    SAFE = "safe"
    CONFIRM = "confirm"
    DANGEROUS = "dangerous"

ToolHandler = Callable[..., Any | Awaitable[Any]]

@dataclass(frozen=True, slots=True)
class RegisteredTool:
    name: str
    description: str
    parameters: Mapping[str, Any]
    risk: ToolRisk
    handler: ToolHandler = field(repr=False, compare=False)

@dataclass(frozen=True, slots=True)
class ToolResult:
    success: bool
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    duration_ms: float = 0.0
    error_type: str | None = None

@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    tool_name: str
    arguments: Mapping[str, Any]
    risk: ToolRisk
    reason: str
