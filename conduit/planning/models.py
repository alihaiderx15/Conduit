"""Structured planning models used by Conduit."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class StepCapability(StrEnum):
    TOOL = "tool"
    BROWSER = "browser"
    DESKTOP = "desktop"
    VISION = "vision"
    USER = "user"


@dataclass(frozen=True, slots=True)
class PlanningCapability:
    name: str
    capability: StepCapability
    description: str
    arguments: Mapping[str, str] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    title: str
    capability: StepCapability
    action: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    requires_confirmation: bool = False
    success_criteria: str = ""


@dataclass(frozen=True, slots=True)
class TaskPlan:
    goal: str
    summary: str
    steps: tuple[PlanStep, ...]
    assumptions: tuple[str, ...] = ()

    @property
    def requires_confirmation(self) -> bool:
        return any(step.requires_confirmation for step in self.steps)


@dataclass(frozen=True, slots=True)
class PlanValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()
