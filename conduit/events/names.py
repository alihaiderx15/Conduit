"""Canonical event names emitted by Conduit modules."""

class EventNames:
    TURN_STARTED = "assistant.turn.started"
    TURN_COMPLETED = "assistant.turn.completed"
    TURN_FAILED = "assistant.turn.failed"
    CONFIRMATION_REQUIRED = "permission.confirmation.required"
    CONFIRMATION_RESOLVED = "permission.confirmation.resolved"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    SCREEN_CAPTURED = "screen.captured"
    DESKTOP_ACTION_STARTED = "desktop.action.started"
    DESKTOP_ACTION_COMPLETED = "desktop.action.completed"
    DESKTOP_ACTION_FAILED = "desktop.action.failed"
    BROWSER_STARTED = "browser.started"
    BROWSER_CLOSED = "browser.closed"
    BROWSER_ACTION_STARTED = "browser.action.started"
    BROWSER_COMPLETED = "browser.action.completed"
    BROWSER_FAILED = "browser.action.failed"
    BROWSER_DOWNLOAD_STARTED = "browser.download.started"
    BROWSER_DOWNLOAD_COMPLETED = "browser.download.completed"

# Planning lifecycle events.
EventNames.PLAN_STARTED = "plan.started"
EventNames.PLAN_COMPLETED = "plan.completed"
EventNames.PLAN_FAILED = "plan.failed"

# Integrated plan-execution lifecycle events.
EventNames.EXECUTION_STARTED = "execution.started"
EventNames.EXECUTION_COMPLETED = "execution.completed"
EventNames.EXECUTION_FAILED = "execution.failed"
EventNames.EXECUTION_STEP_STARTED = "execution.step.started"
EventNames.EXECUTION_STEP_COMPLETED = "execution.step.completed"
EventNames.EXECUTION_STEP_FAILED = "execution.step.failed"
EventNames.EXECUTION_STEP_RETRYING = "execution.step.retrying"
EventNames.EXECUTION_STEP_BLOCKED = "execution.step.blocked"

# Phase 2 iterative-agent lifecycle events.
EventNames.AGENT_STARTED = "agent.started"
EventNames.AGENT_ITERATION_STARTED = "agent.iteration.started"
EventNames.AGENT_DECISION_MADE = "agent.decision.made"
EventNames.AGENT_DECISION_INVALID = "agent.decision.invalid"
EventNames.AGENT_OBSERVATION_RECORDED = "agent.observation.recorded"
EventNames.AGENT_COMPLETED = "agent.completed"
EventNames.AGENT_STOPPED = "agent.stopped"

# Persistent local-memory lifecycle events.
EventNames.MEMORY_SAVED = "memory.saved"
EventNames.MEMORY_RECALLED = "memory.recalled"
EventNames.MEMORY_DELETED = "memory.deleted"

# Agent-memory integration events.
EventNames.MEMORY_INJECTED = "memory.injected"
EventNames.MEMORY_PROPOSED = "memory.proposed"
EventNames.MEMORY_REJECTED = "memory.rejected"
