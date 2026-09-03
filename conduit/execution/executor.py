from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import replace
from time import perf_counter

from conduit.core.models import ToolCall
from conduit.events import EventBus, EventNames
from conduit.tools.errors import ToolEngineError
from conduit.tools.models import PendingConfirmation, ToolResult
from conduit.tools.registry import ToolRegistry
from conduit.tools.validation import validate_arguments

from .permissions import PermissionDecision, PermissionManager

LOGGER = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        permission_manager: PermissionManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.registry = registry
        self.permissions = permission_manager or PermissionManager()
        self.events = event_bus

    async def execute(
        self,
        call: ToolCall,
        *,
        confirmed: bool = False,
    ) -> ToolResult | PendingConfirmation:
        start = perf_counter()
        await self._emit(
            EventNames.TOOL_STARTED,
            {"tool_name": call.name, "arguments": dict(call.arguments), "confirmed": confirmed},
            call.call_id,
        )
        try:
            item = self.registry.get(call.name)
            args = validate_arguments(item.parameters, call.arguments)
            decision = self.permissions.evaluate(item)
            if decision is PermissionDecision.REQUIRE_CONFIRMATION and not confirmed:
                pending = PendingConfirmation(
                    item.name,
                    args,
                    item.risk,
                    f"The tool '{item.name}' requires approval.",
                )
                await self._emit(
                    EventNames.CONFIRMATION_REQUIRED,
                    {
                        "tool_name": item.name,
                        "arguments": dict(args),
                        "risk": item.risk.value,
                        "reason": pending.reason,
                    },
                    call.call_id,
                )
                return pending

            if inspect.iscoroutinefunction(item.handler):
                value = await item.handler(**args)
            else:
                # Run synchronous tools off the event loop so long-running I/O
                # (yt-dlp, filesystem scans, network helpers, etc.) does not make
                # Conduit unresponsive and can be interrupted by the shell.
                value = await asyncio.to_thread(item.handler, **args)
            if inspect.isawaitable(value):
                value = await value
            ms = round((perf_counter() - start) * 1000, 3)
            if isinstance(value, ToolResult):
                result = replace(
                    value,
                    tool_name=value.tool_name or item.name,
                    duration_ms=value.duration_ms or ms,
                )
            else:
                result = ToolResult(
                    True,
                    f"Tool '{item.name}' completed successfully.",
                    {"result": value} if value is not None else {},
                    item.name,
                    ms,
                )
            await self._emit_result(result, call.call_id)
            return result
        except (ToolEngineError, TypeError, ValueError) as exc:
            result = ToolResult(
                False,
                str(exc),
                tool_name=call.name,
                duration_ms=round((perf_counter() - start) * 1000, 3),
                error_type=type(exc).__name__,
            )
            await self._emit_result(result, call.call_id)
            return result
        except Exception as exc:
            LOGGER.exception("Tool failed")
            result = ToolResult(
                False,
                f"Tool '{call.name}' failed: {exc}",
                tool_name=call.name,
                duration_ms=round((perf_counter() - start) * 1000, 3),
                error_type=type(exc).__name__,
            )
            await self._emit_result(result, call.call_id)
            return result

    async def _emit_result(self, result: ToolResult, correlation_id: str | None) -> None:
        await self._emit(
            EventNames.TOOL_COMPLETED if result.success else EventNames.TOOL_FAILED,
            {
                "tool_name": result.tool_name,
                "success": result.success,
                "message": result.message,
                "data": dict(result.data),
                "duration_ms": result.duration_ms,
                "error_type": result.error_type,
            },
            correlation_id,
        )

    async def _emit(
        self,
        name: str,
        payload: dict[str, object],
        correlation_id: str | None,
    ) -> None:
        if self.events is not None:
            await self.events.emit(
                name,
                source="ToolExecutor",
                payload=payload,
                correlation_id=correlation_id,
            )
