"""Small provider wrapper used to verify mid-session recovery behavior."""
from __future__ import annotations
from collections.abc import Sequence
from conduit.core.errors import ProviderAuthenticationError
from conduit.core.models import ChatMessage, ProviderCapabilities, ProviderResponse, ToolDefinition
from .base import AIProvider

class FailAfterNProvider(AIProvider):
    """Delegate normally, then raise a recoverable auth error exactly once."""

    def __init__(self, inner: AIProvider, *, fail_after_calls: int = 1) -> None:
        self.inner = inner
        self.fail_after_calls = max(0, int(fail_after_calls))
        self.calls = 0
        self.failed = False

    @property
    def provider_id(self) -> str:
        return self.inner.provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self.inner.capabilities

    async def list_models(self) -> list[str]:
        return await self.inner.list_models()

    async def model_capabilities(self, model: str) -> ProviderCapabilities:
        return await self.inner.model_capabilities(model)

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        self.calls += 1
        if not self.failed and self.calls > self.fail_after_calls:
            self.failed = True
            raise ProviderAuthenticationError("Simulated Gemini API-key failure during an active task.")
        return await self.inner.chat(messages, model=model, tools=tools)

    async def describe_image(self, *args, **kwargs):
        return await self.inner.describe_image(*args, **kwargs)

    async def close(self) -> None:
        await self.inner.close()
