"""Models for Conduit's unified action layer."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping
from conduit.planning import StepCapability
from conduit.tools import ToolRisk

@dataclass(frozen=True, slots=True)
class ActionDescriptor:
    name: str
    engine: StepCapability
    description: str
    parameters: Mapping[str, Any] = field(default_factory=dict)
    risk: ToolRisk = ToolRisk.SAFE

    @property
    def requires_confirmation(self) -> bool:
        return self.risk is not ToolRisk.SAFE

@dataclass(frozen=True, slots=True)
class ActionOutcome:
    success: bool
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None
