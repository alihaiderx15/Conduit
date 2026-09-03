"""xAI Grok provider using xAI's OpenAI-compatible REST API."""
from __future__ import annotations

import httpx

from conduit.core.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from conduit.providers.openai import OpenAIProvider


class GrokProvider(OpenAIProvider):
    provider_id = "grok"

    def __init__(self, api_key: str) -> None:
        super().__init__(api_key=api_key, base_url="https://api.x.ai/v1")

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.get("/models")
            self._raise_for_response(response, context="model discovery")
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("xAI API is not reachable.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Grok model discovery failed: {exc}") from exc
        payload = response.json()
        return sorted(
            str(item.get("id", "")).strip()
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )

    async def _request(self, path: str, payload: dict, *, context: str):
        try:
            response = await self._client.post(path, json=payload)
            self._raise_for_response(response, context=context)
            return response
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("xAI API is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"Grok {context} request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Grok {context} request failed: {exc}") from exc

    @staticmethod
    def _raise_for_response(response: httpx.Response, *, context: str) -> None:
        if response.is_success:
            return
        detail = response.text.strip()
        code = response.status_code
        if code in (401, 403):
            raise ProviderAuthenticationError(
                f"xAI credentials were rejected ({code}): {detail}"
            )
        if code == 429:
            raise ProviderQuotaError(f"Grok quota/rate limit is unavailable: {detail}")
        if code >= 500:
            raise ProviderUnavailableError(
                f"xAI service is unavailable ({code}): {detail}"
            )
        raise ProviderError(f"Grok {context} request failed ({code}): {detail}")
