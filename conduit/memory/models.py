"""Typed models for Conduit's persistent local memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class MemoryCategory(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"
    PROJECT = "project"
    CONVERSATION = "conversation"
    TASK = "task"
    DIRECTIVE = "directive"
    HABIT = "habit"
    RECAP = "recap"


@dataclass(frozen=True, slots=True)
class Conversation:
    id: int
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    id: int
    category: MemoryCategory
    key: str
    value: str
    importance: float
    source: str
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    id: int
    name: str
    description: str
    path: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectFact:
    id: int
    project_id: int
    key: str
    value: str
    importance: float
    source: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SearchResult:
    record: MemoryRecord
    score: float


@dataclass(frozen=True, slots=True)
class BehaviorRecord:
    id: int
    kind: str
    value: str
    count: int
    score: float
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DirectiveRecord:
    id: int
    scope: str
    key: str
    value: str
    source_text: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class SessionRecap:
    id: int
    summary: str
    created_at: datetime
    consumed_at: datetime | None
    metadata: dict[str, Any]
