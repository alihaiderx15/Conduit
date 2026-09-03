"""Conversation orchestrator connecting providers, tools, and permissions."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Sequence

from conduit.core.models import ChatMessage, Role, ToolCall
from conduit.events import EventBus, EventNames
from conduit.execution.executor import ToolExecutor
from conduit.providers.base import AIProvider
from conduit.tools.models import PendingConfirmation, ToolResult
from conduit.tools.registry import ToolRegistry

from .models import AssistantTurn, TurnStatus


DEFAULT_SYSTEM_PROMPT = """You are Conduit, a calm, capable desktop assistant.
Use available tools when they are needed to complete the user's request.
Never claim a tool succeeded unless the tool result confirms success.
When a tool result is provided, answer the user with a concise completion or error message.
Do not invent tool results. Ask for clarification when the request is ambiguous.
"""


class AssistantOrchestrator:
    """Runs the provider -> tool -> provider conversation loop."""

    def __init__(
        self,
        *,
        provider: AIProvider,
        model: str,
        registry: ToolRegistry,
        executor: ToolExecutor,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_rounds: int = 6,
        event_bus: EventBus | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("A model name is required.")
        if max_tool_rounds < 1:
            raise ValueError("max_tool_rounds must be at least 1.")
        self.provider = provider
        self.model = model
        self.registry = registry
        self.executor = executor
        self.max_tool_rounds = max_tool_rounds
        self.events = event_bus
        self._messages: list[ChatMessage] = [
            ChatMessage(Role.SYSTEM, system_prompt.strip())
        ]
        self._pending_call: ToolCall | None = None
        self._pending_context: list[ChatMessage] | None = None

    @property
    def history(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    @property
    def has_pending_confirmation(self) -> bool:
        return self._pending_call is not None

    async def submit(self, user_text: str) -> AssistantTurn:
        """Process a normal user message or a pending confirmation response."""
        text = user_text.strip()
        if not text:
            return AssistantTurn(TurnStatus.FAILED, "Please enter a request.")

        if self._pending_call is not None:
            return await self._resolve_confirmation(text)

        self._messages.append(ChatMessage(Role.USER, text))
        await self._emit(EventNames.TURN_STARTED, {"user_text": text})
        turn = await self._run_loop(list(self._messages))
        await self._emit_turn_result(turn)
        return turn

    async def _resolve_confirmation(self, text: str) -> AssistantTurn:
        normalized = text.casefold().strip()
        if normalized in {"cancel", "no", "n", "deny", "stop"}:
            self._clear_pending()
            message = "The operation has been cancelled."
            self._messages.append(ChatMessage(Role.ASSISTANT, message))
            turn = AssistantTurn(TurnStatus.COMPLETED, message)
            await self._emit(
                EventNames.CONFIRMATION_RESOLVED,
                {"approved": False, "message": message},
            )
            await self._emit_turn_result(turn)
            return turn

        if normalized not in {"yes", "y", "confirm", "approve", "proceed"}:
            pending = await self._pending_preview()
            return AssistantTurn(
                TurnStatus.AWAITING_CONFIRMATION,
                "Please reply with 'yes' to proceed or 'cancel' to stop.",
                pending_confirmation=pending,
            )

        assert self._pending_call is not None
        call = self._pending_call
        context = list(self._pending_context or self._messages)
        self._clear_pending()
        await self._emit(
            EventNames.CONFIRMATION_RESOLVED,
            {"approved": True, "tool_name": call.name},
            call.call_id,
        )
        result = await self.executor.execute(call, confirmed=True)
        if isinstance(result, PendingConfirmation):
            return AssistantTurn(
                TurnStatus.FAILED,
                "The permission system did not accept the confirmation.",
            )
        context.append(self._tool_result_message(call, result))
        self._messages = context
        return await self._run_loop(context, previous_results=[result])

    async def _pending_preview(self) -> PendingConfirmation | None:
        if self._pending_call is None:
            return None
        outcome = await self.executor.execute(self._pending_call, confirmed=False)
        return outcome if isinstance(outcome, PendingConfirmation) else None

    async def _run_loop(
        self,
        context: list[ChatMessage],
        *,
        previous_results: Sequence[ToolResult] = (),
    ) -> AssistantTurn:
        results = list(previous_results)
        for round_index in range(self.max_tool_rounds):
            response = await self.provider.chat(
                context,
                model=self.model,
                tools=self.registry.definitions(),
            )

            if response.text.strip():
                context.append(ChatMessage(Role.ASSISTANT, response.text.strip()))

            if not response.tool_calls:
                final_text = response.text.strip() or self._fallback_message(results)
                if not response.text.strip():
                    context.append(ChatMessage(Role.ASSISTANT, final_text))
                self._messages = context
                return AssistantTurn(
                    TurnStatus.COMPLETED,
                    final_text,
                    tool_results=tuple(results),
                    metadata={"tool_rounds": round_index},
                )

            for call in response.tool_calls:
                outcome = await self.executor.execute(call, confirmed=False)
                if isinstance(outcome, PendingConfirmation):
                    self._pending_call = call
                    self._pending_context = list(context)
                    self._messages = list(context)
                    return AssistantTurn(
                        TurnStatus.AWAITING_CONFIRMATION,
                        self._confirmation_message(outcome),
                        tool_results=tuple(results),
                        pending_confirmation=outcome,
                        metadata={"tool_rounds": round_index + 1},
                    )

                results.append(outcome)
                context.append(self._tool_result_message(call, outcome))

        message = (
            "I stopped the task because it exceeded the maximum number of tool rounds."
        )
        context.append(ChatMessage(Role.ASSISTANT, message))
        self._messages = context
        return AssistantTurn(
            TurnStatus.FAILED,
            message,
            tool_results=tuple(results),
            metadata={"tool_rounds": self.max_tool_rounds},
        )

    async def _emit(
        self,
        name: str,
        payload: dict[str, object],
        correlation_id: str | None = None,
    ) -> None:
        if self.events is not None:
            await self.events.emit(
                name,
                source="AssistantOrchestrator",
                payload=payload,
                correlation_id=correlation_id,
            )

    async def _emit_turn_result(self, turn: AssistantTurn) -> None:
        name = (
            EventNames.TURN_COMPLETED
            if turn.status is TurnStatus.COMPLETED
            else EventNames.TURN_FAILED
        )
        await self._emit(
            name,
            {
                "status": turn.status.value,
                "message": turn.message,
                "tool_results": len(turn.tool_results),
            },
        )

    @staticmethod
    def _tool_result_message(call: ToolCall, result: ToolResult) -> ChatMessage:
        payload = {
            "tool_call_id": call.call_id,
            "tool_name": call.name,
            "success": result.success,
            "message": result.message,
            "data": dict(result.data),
            "error_type": result.error_type,
            "duration_ms": result.duration_ms,
        }
        return ChatMessage(Role.TOOL, json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _confirmation_message(pending: PendingConfirmation) -> str:
        arguments = json.dumps(dict(pending.arguments), ensure_ascii=False)
        return (
            f"This operation requires confirmation: {pending.tool_name} {arguments}. "
            "Reply 'yes' to proceed or 'cancel' to stop."
        )

    @staticmethod
    def _fallback_message(results: Sequence[ToolResult]) -> str:
        if not results:
            return "The request has been processed."
        last = results[-1]
        return last.message

    def _clear_pending(self) -> None:
        self._pending_call = None
        self._pending_context = None
