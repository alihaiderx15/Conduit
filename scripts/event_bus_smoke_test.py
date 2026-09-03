"""Manual smoke test for Conduit Module 7A: Event Bus."""

from __future__ import annotations

import asyncio

from conduit.core.models import ToolCall
from conduit.events import Event, EventBus
from conduit.execution.executor import ToolExecutor
from conduit.tools.builtin import registry


def print_event(event: Event) -> None:
    print(
        f"EVENT {event.name}\n"
        f"  source: {event.source}\n"
        f"  correlation: {event.correlation_id}\n"
        f"  payload: {dict(event.payload)}\n"
    )


async def main() -> None:
    bus = EventBus()
    bus.subscribe("*", print_event)
    executor = ToolExecutor(registry, event_bus=bus)

    print("Publishing a custom event...\n")
    report = await bus.emit(
        "conduit.smoke.started",
        source="event_bus_smoke_test",
        payload={"module": "7A"},
    )
    print(f"Custom event delivered to {report.delivered} subscriber(s).\n")

    print("Executing the safe Calculator tool...\n")
    result = await executor.execute(
        ToolCall(name="open_calculator", arguments={}, call_id="event-smoke-calculator")
    )
    print(f"RESULT: {result}\n")

    print("Requesting a protected folder action without approval...\n")
    pending = await executor.execute(
        ToolCall(
            name="create_folder",
            arguments={"path": "Conduit Event Bus Smoke Test"},
            call_id="event-smoke-confirmation",
        )
    )
    print(f"PENDING: {pending}\n")
    print("No folder was created because confirmation was not granted.")


if __name__ == "__main__":
    asyncio.run(main())
