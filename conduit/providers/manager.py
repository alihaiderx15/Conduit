"""Provider registration and selection."""

from __future__ import annotations

from conduit.core.errors import ProviderConfigurationError
from conduit.providers.base import AIProvider


class ProviderManager:
    """Owns configured providers without exposing provider-specific details."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}
        self._active_id: str | None = None

    def register(self, provider: AIProvider, *, make_active: bool = False) -> None:
        provider_id = provider.provider_id.strip().lower()
        if not provider_id:
            raise ProviderConfigurationError("Provider ID cannot be empty.")
        self._providers[provider_id] = provider
        if make_active or self._active_id is None:
            self._active_id = provider_id

    def set_active(self, provider_id: str) -> None:
        normalized = provider_id.strip().lower()
        if normalized not in self._providers:
            raise ProviderConfigurationError(
                f"Provider '{provider_id}' is not registered."
            )
        self._active_id = normalized

    @property
    def active(self) -> AIProvider:
        if self._active_id is None:
            raise ProviderConfigurationError("No provider has been configured.")
        return self._providers[self._active_id]

    def get(self, provider_id: str) -> AIProvider:
        normalized = provider_id.strip().lower()
        try:
            return self._providers[normalized]
        except KeyError as exc:
            raise ProviderConfigurationError(
                f"Provider '{provider_id}' is not registered."
            ) from exc

    def available(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    async def close(self) -> None:
        for provider in self._providers.values():
            await provider.close()
