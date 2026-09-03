"""Small async-aware event bus for decoupled Conduit modules."""

from __future__ import annotations

import asyncio
import fnmatch
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .models import DeliveryFailure, DeliveryReport, Event, Subscription

LOGGER = logging.getLogger(__name__)
EventHandler = Callable[[Event], Any | Awaitable[Any]]


@dataclass(slots=True)
class _Subscriber:
    subscription: Subscription
    handler: EventHandler


class EventBus:
    """Publish immutable events to exact or wildcard subscriptions.

    Patterns use shell-style matching. Examples: ``tool.started``, ``tool.*``,
    and ``*``. A failing subscriber never prevents delivery to other subscribers.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, _Subscriber] = {}

    def subscribe(self, pattern: str, handler: EventHandler) -> Subscription:
        normalized = pattern.strip()
        if not normalized:
            raise ValueError("Subscription pattern cannot be empty.")
        if not callable(handler):
            raise TypeError("Event handler must be callable.")
        subscription = Subscription(token=uuid4().hex, pattern=normalized)
        self._subscribers[subscription.token] = _Subscriber(subscription, handler)
        return subscription

    def unsubscribe(self, subscription: Subscription | str) -> bool:
        token = subscription.token if isinstance(subscription, Subscription) else str(subscription)
        return self._subscribers.pop(token, None) is not None

    def clear(self) -> None:
        self._subscribers.clear()

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def _matches(self, event_name: str) -> tuple[_Subscriber, ...]:
        return tuple(
            subscriber
            for subscriber in self._subscribers.values()
            if fnmatch.fnmatchcase(event_name, subscriber.subscription.pattern)
        )

    async def publish(self, event: Event) -> DeliveryReport:
        failures: list[DeliveryFailure] = []
        delivered = 0
        for subscriber in self._matches(event.name):
            try:
                result = subscriber.handler(event)
                if inspect.isawaitable(result):
                    await result
                delivered += 1
            except Exception as exc:  # Subscriber failures must be isolated.
                LOGGER.exception("Event subscriber failed for %s", event.name)
                failures.append(
                    DeliveryFailure(
                        subscription_token=subscriber.subscription.token,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
        return DeliveryReport(event=event, delivered=delivered, failures=tuple(failures))

    async def emit(
        self,
        name: str,
        *,
        source: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> DeliveryReport:
        return await self.publish(
            Event(
                name=name,
                source=source,
                payload=payload or {},
                correlation_id=correlation_id,
            )
        )

    def publish_nowait(self, event: Event) -> None:
        """Deliver sync handlers immediately and schedule async handlers.

        This method is intended for synchronous components such as screenshot
        capture and PyAutoGUI. Subscriber exceptions are logged and isolated.
        """
        for subscriber in self._matches(event.name):
            try:
                result = subscriber.handler(event)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        # Synchronous desktop actions may emit from worker threads
                        # where no asyncio loop exists. Close coroutine objects so
                        # Python does not produce "was never awaited" warnings.
                        close = getattr(result, "close", None)
                        if callable(close):
                            close()
                        LOGGER.debug(
                            "Async event handler skipped because no event loop is running: %s",
                            event.name,
                        )
                    else:
                        loop.create_task(self._consume_background(result, event.name))
            except Exception:
                LOGGER.exception("Event subscriber failed for %s", event.name)

    def emit_nowait(
        self,
        name: str,
        *,
        source: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> Event:
        event = Event(
            name=name,
            source=source,
            payload=payload or {},
            correlation_id=correlation_id,
        )
        self.publish_nowait(event)
        return event

    @staticmethod
    async def _consume_background(awaitable: Awaitable[Any], event_name: str) -> None:
        try:
            await awaitable
        except Exception:
            LOGGER.exception("Background event subscriber failed for %s", event_name)
