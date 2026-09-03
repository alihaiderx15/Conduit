from __future__ import annotations

from collections import deque

import pytest

from conduit.assistant import AssistantOrchestrator, TurnStatus
from conduit.core.models import ProviderCapabilities, ProviderResponse, ToolCall
from conduit.execution.executor import ToolExecutor
from conduit.providers.base import AIProvider
from conduit.tools.models import ToolRisk
from conduit.tools.registry import ToolRegistry, tool


class ScriptedProvider(AIProvider):
    provider_id = "scripted"

    def __init__(self, responses):
        self.responses = deque(responses)
        self.calls = []

    @property
    def capabilities(self):
        return ProviderCapabilities()

    async def list_models(self):
        return ["test-model"]

    async def chat(self, messages, *, model, tools=()):
        self.calls.append((tuple(messages), tuple(tools)))
        return self.responses.popleft()


@pytest.mark.asyncio
async def test_safe_tool_runs_and_result_returns_to_model():
    registry = ToolRegistry()
    opened = []

    @tool(registry, name="open_calculator", description="Open calculator")
    def open_calculator():
        opened.append(True)
        return "opened"

    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("open_calculator", {}),)),
        ProviderResponse(text="Calculator is now open."),
    ])
    orchestrator = AssistantOrchestrator(
        provider=provider,
        model="test-model",
        registry=registry,
        executor=ToolExecutor(registry),
    )

    turn = await orchestrator.submit("Open calculator")

    assert turn.status is TurnStatus.COMPLETED
    assert turn.message == "Calculator is now open."
    assert opened == [True]
    assert turn.tool_results[0].success is True
    assert any(message.role.value == "tool" for message in provider.calls[1][0])


@pytest.mark.asyncio
async def test_confirmation_pauses_then_resumes():
    registry = ToolRegistry()
    created = []

    @tool(
        registry,
        name="create_folder",
        description="Create folder",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        risk=ToolRisk.CONFIRM,
    )
    def create_folder(path: str):
        created.append(path)
        return path

    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("create_folder", {"path": "Demo"}),)),
        ProviderResponse(text="The folder has been created successfully."),
    ])
    orchestrator = AssistantOrchestrator(
        provider=provider,
        model="test-model",
        registry=registry,
        executor=ToolExecutor(registry),
    )

    pending = await orchestrator.submit("Create Demo folder")
    assert pending.status is TurnStatus.AWAITING_CONFIRMATION
    assert created == []

    completed = await orchestrator.submit("yes")
    assert completed.status is TurnStatus.COMPLETED
    assert created == ["Demo"]
    assert completed.message == "The folder has been created successfully."


@pytest.mark.asyncio
async def test_confirmation_can_be_cancelled():
    registry = ToolRegistry()
    called = []

    @tool(registry, name="danger", description="Danger", risk=ToolRisk.DANGEROUS)
    def danger():
        called.append(True)

    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("danger", {}),)),
    ])
    orchestrator = AssistantOrchestrator(
        provider=provider,
        model="test-model",
        registry=registry,
        executor=ToolExecutor(registry),
    )

    await orchestrator.submit("Do danger")
    result = await orchestrator.submit("cancel")

    assert result.status is TurnStatus.COMPLETED
    assert "cancelled" in result.message.lower()
    assert called == []


@pytest.mark.asyncio
async def test_invalid_confirmation_keeps_pending_state():
    registry = ToolRegistry()

    @tool(registry, name="confirm_me", description="Confirm", risk=ToolRisk.CONFIRM)
    def confirm_me():
        return None

    provider = ScriptedProvider([
        ProviderResponse(tool_calls=(ToolCall("confirm_me", {}),)),
    ])
    orchestrator = AssistantOrchestrator(
        provider=provider,
        model="test-model",
        registry=registry,
        executor=ToolExecutor(registry),
    )

    await orchestrator.submit("Run it")
    result = await orchestrator.submit("maybe")

    assert result.status is TurnStatus.AWAITING_CONFIRMATION
    assert orchestrator.has_pending_confirmation is True
