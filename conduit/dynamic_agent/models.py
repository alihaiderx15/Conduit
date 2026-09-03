"""Models for Conduit's iterative Phase 2 agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from conduit.memory.integration import MemoryProposal, MemoryProposalResult


class AgentDecisionKind(StrEnum):
    ACT = "act"
    FINISH = "finish"
    FAIL = "fail"
    ASK_USER = "ask_user"


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_FOR_USER = "waiting_for_user"
    MAX_ITERATIONS = "max_iterations"


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """One model-selected next decision."""

    kind: AgentDecisionKind
    reason: str
    action: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    message: str = ""
    save_as: Mapping[str, str] = field(default_factory=dict)
    memory_proposals: tuple[MemoryProposal, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """Result of one action attempted by the dynamic agent."""

    iteration: int
    action: str
    arguments: Mapping[str, Any]
    success: bool
    message: str
    data: Mapping[str, Any] = field(default_factory=dict)
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class AgentRunReport:
    """Final report from an iterative agent run."""

    goal: str
    status: AgentRunStatus
    success: bool
    final_message: str
    observations: tuple[AgentObservation, ...]
    variables: Mapping[str, Any]
    iterations: int
    pending_question: str | None = None
    relevant_memories: tuple[str, ...] = ()
    memory_proposal_results: tuple[MemoryProposalResult, ...] = ()
