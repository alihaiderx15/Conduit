"""Models used by the assistant orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Any

from conduit.tools.models import PendingConfirmation, ToolResult


class TurnStatus(str, Enum):
    COMPLETED = "completed"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    """Structured result returned after processing one user turn."""

    status: TurnStatus
    message: str
    tool_results: tuple[ToolResult, ...] = ()
    pending_confirmation: PendingConfirmation | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
