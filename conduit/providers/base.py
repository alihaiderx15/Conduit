"""Provider interface shared by Gemini, Ollama, and future adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Sequence

from conduit.core.models import (
    ChatMessage,
    ProviderCapabilities,
    ProviderResponse,
    ToolDefinition,
)


class AIProvider(ABC):
    """Stable contract used by the rest of Conduit."""

    provider_id: str

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    @abstractmethod
    async def list_models(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        raise NotImplementedError

    async def specialist_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        """Run a narrow internal task without requiring global assistant context.

        Providers may override this to omit Conduit's large core identity prompt.
        The default preserves compatibility with third-party/test providers.
        """
        return await self.chat(messages, model=model, tools=tools)

    async def specialist_chat_with_progress(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
        on_progress=None,
    ) -> ProviderResponse:
        """Specialist request with optional progress heartbeats."""
        if on_progress is not None:
            on_progress(0, "request dispatched")
        response = await self.specialist_chat(messages, model=model, tools=tools)
        if on_progress is not None:
            on_progress(max(1, len(response.text)), "response complete")
        return response

    async def describe_image(
        self,
        image_path: Path,
        prompt: str,
        *,
        model: str,
    ) -> ProviderResponse:
        raise NotImplementedError(f"{self.provider_id} does not implement vision")

    async def model_capabilities(self, model: str) -> ProviderCapabilities:
        """Return capabilities for a selected model when discoverable."""
        return self.capabilities

    async def close(self) -> None:
        """Release provider resources. Implementations may override."""
