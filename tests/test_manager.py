from pathlib import Path
from typing import Sequence

import pytest

from conduit.core.models import (
    ChatMessage,
    ProviderCapabilities,
    ProviderResponse,
    ToolDefinition,
)
from conduit.providers.base import AIProvider
from conduit.providers.manager import ProviderManager


class FakeProvider(AIProvider):
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()

    async def list_models(self) -> list[str]:
        return ["test"]

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        return ProviderResponse(text="ok", model=model)


@pytest.mark.asyncio
async def test_manager_switches_provider() -> None:
    manager = ProviderManager()
    manager.register(FakeProvider("gemini"), make_active=True)
    manager.register(FakeProvider("ollama"))
    assert manager.active.provider_id == "gemini"
    manager.set_active("ollama")
    assert manager.active.provider_id == "ollama"
    await manager.close()
