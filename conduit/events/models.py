"""Typed event models used by Conduit's internal event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    """One immutable event published by a Conduit component."""

    name: str
    source: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Event name cannot be empty.")
        if not self.source.strip():
            raise ValueError("Event source cannot be empty.")


@dataclass(frozen=True, slots=True)
class Subscription:
    """Opaque subscription handle returned by EventBus.subscribe."""

    token: str
    pattern: str


@dataclass(frozen=True, slots=True)
class DeliveryFailure:
    """Information about one subscriber that failed while handling an event."""

    subscription_token: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class DeliveryReport:
    """Summary of event delivery across all matching subscribers."""

    event: Event
    delivered: int
    failures: tuple[DeliveryFailure, ...] = ()

    @property
    def succeeded(self) -> bool:
        return not self.failures
