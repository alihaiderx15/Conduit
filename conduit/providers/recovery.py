"""Provider hot-swap support for long-running agent sessions."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable, Callable
from conduit.core.errors import ProviderError
from .base import AIProvider

@dataclass(slots=True)
class ProviderReplacement:
    provider: AIProvider
    model: str
    reason: str = ""

ProviderRecoveryHandler = Callable[[ProviderError, AIProvider, str], Awaitable[ProviderReplacement | None]]
