"""Dynamic Phase 2 agent loop."""

from .context import AgentContext, ContextVariable, VariableResolutionError, VariableStore
from .loop import DynamicAgentLoop
from .models import (
    AgentDecision,
    AgentDecisionKind,
    AgentObservation,
    AgentRunReport,
    AgentRunStatus,
)
from .parser import AgentDecisionError, parse_decision

__all__ = [
    "AgentContext",
    "ContextVariable",
    "AgentDecision",
    "AgentDecisionError",
    "AgentDecisionKind",
    "AgentObservation",
    "AgentRunReport",
    "AgentRunStatus",
    "DynamicAgentLoop",
    "VariableResolutionError",
    "VariableStore",
    "parse_decision",
]

from .completion import (
    CompletionEvidence,
    CompletionVerifier,
    StructuredFileGoalVerifier,
    WindowsClipboardProcessVerifier,
    CompositeCompletionVerifier,
    RecentFileNotepadVerifier,
    ConversationalWebActionVerifier,
)
