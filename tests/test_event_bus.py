from __future__ import annotations

import asyncio

import pytest

from conduit.events import Event, EventBus


@pytest.mark.asyncio
async def test_exact_and_wildcard_subscriptions_receive_event() -> None:
    bus = EventBus()
    received: list[tuple[str, str]] = []

    bus.subscribe("tool.started", lambda event: received.append(("exact", event.name)))
    bus.subscribe("tool.*", lambda event: received.append(("wildcard", event.name)))
    bus.subscribe("*", lambda event: received.append(("all", event.name)))

    report = await bus.emit("tool.started", source="test", payload={"name": "demo"})

    assert report.delivered == 3
    assert report.succeeded
    assert received == [
        ("exact", "tool.started"),
        ("wildcard", "tool.started"),
        ("all", "tool.started"),
    ]


@pytest.mark.asyncio
async def test_async_subscriber_is_awaited() -> None:
    bus = EventBus()
    received: list[str] = []

    async def handler(event: Event) -> None:
        await asyncio.sleep(0)
        received.append(event.name)

    bus.subscribe("screen.*", handler)
    report = await bus.emit("screen.captured", source="test")

    assert report.delivered == 1
    assert received == ["screen.captured"]


@pytest.mark.asyncio
async def test_subscriber_failure_is_isolated() -> None:
    bus = EventBus()
    received: list[str] = []

    def broken(_: Event) -> None:
        raise RuntimeError("subscriber failed")

    bus.subscribe("tool.*", broken)
    bus.subscribe("tool.*", lambda event: received.append(event.name))

    report = await bus.emit("tool.completed", source="test")

    assert report.delivered == 1
    assert len(report.failures) == 1
    assert report.failures[0].error_type == "RuntimeError"
    assert received == ["tool.completed"]


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    received: list[str] = []
    subscription = bus.subscribe("*", lambda event: received.append(event.name))

    assert bus.unsubscribe(subscription)
    assert not bus.unsubscribe(subscription)
    bus.emit_nowait("demo.event", source="test")

    assert received == []


def test_publish_nowait_delivers_sync_handlers_immediately() -> None:
    bus = EventBus()
    received: list[str] = []
    bus.subscribe("desktop.*", lambda event: received.append(event.name))

    event = bus.emit_nowait("desktop.action.started", source="test")

    assert received == ["desktop.action.started"]
    assert event.source == "test"


def test_event_requires_name_and_source() -> None:
    with pytest.raises(ValueError):
        Event(name="", source="test")
    with pytest.raises(ValueError):
        Event(name="demo", source="")
