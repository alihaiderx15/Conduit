"""OpenAI API provider using standard HTTPS endpoints."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Sequence

import httpx

from conduit.core.errors import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderQuotaError,
    ProviderUnavailableError,
)
from conduit.core.models import (
    ChatMessage,
    ProviderCapabilities,
    ProviderResponse,
    Role,
    ToolCall,
    ToolDefinition,
)
from conduit.core.prompting import with_core_prompt
from conduit.providers.base import AIProvider


class OpenAIProvider(AIProvider):
    provider_id = "openai"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        key = api_key.strip()
        if not key:
            raise ProviderConfigurationError("OpenAI API key is required.")
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=120.0,
            headers={"Authorization": f"Bearer {key}"},
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True, tools=True, vision=True, streaming=False)

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.get("/models")
            self._raise_for_response(response, context="model discovery")
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("OpenAI API is not reachable.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI model discovery failed: {exc}") from exc
        payload = response.json()
        return sorted(
            str(item.get("id", "")).strip()
            for item in payload.get("data", [])
            if isinstance(item, dict) and item.get("id")
        )

    async def model_capabilities(self, model: str) -> ProviderCapabilities:
        if not model.strip():
            raise ProviderConfigurationError("An OpenAI model must be selected.")
        # The selected model is validated with an actual request when switching.
        # Conduit's OpenAI path targets current multimodal GPT models.
        return self.capabilities

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        if not model.strip():
            raise ProviderConfigurationError("An OpenAI model must be selected.")
        messages = with_core_prompt(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": _role(message.role), "content": message.content}
                for message in messages
                if message.role is not Role.TOOL
            ],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in tools
            ]
            payload["tool_choice"] = "auto"

        response = await self._request("/chat/completions", payload, context="chat")
        data = response.json()
        choices = data.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}

        calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls", []) or []):
            function = call.get("function", {}) or {}
            arguments = function.get("arguments", {}) or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
            calls.append(
                ToolCall(
                    name=str(function.get("name", "")),
                    arguments=dict(arguments),
                    call_id=str(call.get("id") or index),
                )
            )

        return ProviderResponse(
            text=str(message.get("content") or ""),
            tool_calls=tuple(calls),
            model=str(data.get("model") or model),
            raw=data,
        )

    async def specialist_chat_with_progress(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
        on_progress=None,
    ) -> ProviderResponse:
        if tools:
            return await super().specialist_chat_with_progress(
                messages, model=model, tools=tools, on_progress=on_progress
            )
        if not model.strip():
            raise ProviderConfigurationError("A model must be selected.")

        payload = {
            "model": model,
            "messages": [
                {"role": _role(message.role), "content": message.content}
                for message in messages
                if message.role is not Role.TOOL
            ],
            "stream": True,
        }
        chunks: list[str] = []
        raw_events: list[dict[str, Any]] = []
        timeout = httpx.Timeout(connect=30.0, read=None, write=120.0, pool=60.0)
        try:
            async with self._client.stream(
                "POST", "/chat/completions", json=payload, timeout=timeout
            ) as response:
                self._raise_for_response(response, context="streaming specialist chat")
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data_text = line[5:].strip()
                    if data_text == "[DONE]":
                        break
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    raw_events.append(event)
                    choices = event.get("choices", [])
                    delta = choices[0].get("delta", {}) if choices else {}
                    text = str(delta.get("content") or "")
                    if text:
                        chunks.append(text)
                        if on_progress is not None:
                            on_progress(len(text), f"{self.provider_id} is generating code")
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(f"{self.provider_id} API is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"{self.provider_id} streaming request timed out at the network layer."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.provider_id} streaming request failed: {exc}") from exc

        return ProviderResponse(
            text="".join(chunks),
            model=model,
            raw={"stream_events": raw_events[-20:]},
        )

    async def describe_image(
        self,
        image_path: Path,
        prompt: str,
        *,
        model: str,
    ) -> ProviderResponse:
        if not image_path.is_file():
            raise ProviderConfigurationError(f"Image not found: {image_path}")
        mime = _mime_type(image_path)
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{encoded}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 1200,
        }
        response = await self._request(
            "/chat/completions",
            payload,
            context="vision",
        )
        data = response.json()
        choices = data.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        return ProviderResponse(
            text=str(message.get("content") or ""),
            model=str(data.get("model") or model),
            raw=data,
        )

    async def _request(self, path: str, payload: dict[str, Any], *, context: str):
        try:
            response = await self._client.post(path, json=payload)
            self._raise_for_response(response, context=context)
            return response
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("OpenAI API is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"OpenAI {context} request timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenAI {context} request failed: {exc}") from exc

    @staticmethod
    def _raise_for_response(response: httpx.Response, *, context: str) -> None:
        if response.is_success:
            return
        detail = response.text.strip()
        code = response.status_code
        if code in (401, 403):
            raise ProviderAuthenticationError(
                f"OpenAI credentials were rejected ({code}): {detail}"
            )
        if code == 429:
            raise ProviderQuotaError(f"OpenAI quota/rate limit is unavailable: {detail}")
        if code >= 500:
            raise ProviderUnavailableError(
                f"OpenAI service is unavailable ({code}): {detail}"
            )
        raise ProviderError(f"OpenAI {context} request failed ({code}): {detail}")

    async def close(self) -> None:
        await self._client.aclose()


def _role(role: Role) -> str:
    return {
        Role.SYSTEM: "system",
        Role.USER: "user",
        Role.ASSISTANT: "assistant",
        Role.TOOL: "tool",
    }[role]


def _mime_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(path.suffix.casefold(), "application/octet-stream")
