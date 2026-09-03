"""Structured plan-execution models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from conduit.planning import PlanStep, TaskPlan


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class StepExecutionResult:
    step: PlanStep
    status: StepStatus
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    attempts: int = 1
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class PlanExecutionReport:
    plan: TaskPlan
    success: bool
    results: tuple[StepExecutionResult, ...]
    final_message: str

    @property
    def completed_steps(self) -> tuple[StepExecutionResult, ...]:
        return tuple(item for item in self.results if item.status is StepStatus.COMPLETED)
