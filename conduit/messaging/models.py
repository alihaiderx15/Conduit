"""Structured models for Conduit's messaging capability."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class MessagingPlan:
    action: str
    service: str
    recipient: str = ""
    message: str = ""
    compose_instruction: str = ""
    count: int = 5


@dataclass(frozen=True, slots=True)
class MessagingClient:
    service: str
    mode: str
    app_name: str = ""
    window_title: str = ""
    web_url: str = ""


@dataclass(frozen=True, slots=True)
class ContactCandidate:
    label: str
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
