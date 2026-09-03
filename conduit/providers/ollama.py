"""Ollama provider using its native local HTTP API."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Sequence

import httpx

from conduit.core.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderUnavailableError,
)
from conduit.core.models import (
    ChatMessage,
    ProviderCapabilities,
    ProviderResponse,
    ToolCall,
    ToolDefinition,
)
from conduit.core.schema import ollama_tool_dict
from conduit.providers.base import AIProvider
from conduit.core.prompting import with_core_prompt


class OllamaProvider(AIProvider):
    provider_id = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        *,
        num_ctx: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        configured = num_ctx
        if configured is None:
            try:
                configured = int(os.getenv("CONDUIT_OLLAMA_NUM_CTX", "8192"))
            except ValueError:
                configured = 8192
        self._num_ctx = max(4096, int(configured))
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=120.0)

    @property
    def capabilities(self) -> ProviderCapabilities:
        # Vision depends on the selected model, but the transport supports it.
        return ProviderCapabilities(chat=True, tools=True, vision=True, streaming=False)

    async def list_models(self) -> list[str]:
        try:
            response = await self._client.get("/api/tags")
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "Ollama is not reachable. Start Ollama and try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama model discovery failed: {exc}") from exc

        payload = response.json()
        return sorted(
            str(item.get("name") or item.get("model"))
            for item in payload.get("models", [])
            if item.get("name") or item.get("model")
        )

    async def model_capabilities(self, model: str) -> ProviderCapabilities:
        if not model.strip():
            raise ProviderConfigurationError("An Ollama model must be selected.")
        try:
            response = await self._client.post("/api/show", json={"model": model})
            response.raise_for_status()
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "Ollama is not reachable. Start Ollama and try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama capability discovery failed: {exc}") from exc
        capabilities = {str(item).lower() for item in response.json().get("capabilities", [])}
        return ProviderCapabilities(
            chat=True,
            tools="tools" in capabilities or "tool" in capabilities,
            vision="vision" in capabilities,
            streaming=True,
        )

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        return await self._chat_impl(
            with_core_prompt(messages),
            model=model,
            tools=tools,
        )

    async def specialist_chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        """Lean internal call: deliberately omit the full Conduit core prompt."""
        return await self._chat_impl(
            tuple(messages),
            model=model,
            tools=tools,
        )

    async def _chat_impl(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        if not model.strip():
            raise ProviderConfigurationError("An Ollama model must be selected.")

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "stream": False,
            "options": {"num_ctx": self._num_ctx},
        }
        if tools:
            payload["tools"] = [
                ollama_tool_dict(tool.name, tool.description, tool.parameters)
                for tool in tools
            ]

        data = await self._post_chat(payload)
        message = data.get("message", {})
        calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls", []) or []):
            function = call.get("function", {})
            arguments = function.get("arguments", {}) or {}
            calls.append(
                ToolCall(
                    name=str(function.get("name", "")),
                    arguments=dict(arguments),
                    call_id=str(call.get("id") or index),
                )
            )

        return ProviderResponse(
            text=str(message.get("content", "") or ""),
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
            raise ProviderConfigurationError("An Ollama model must be selected.")

        payload = {
            "model": model,
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in messages
            ],
            "stream": True,
            "options": {"num_ctx": self._num_ctx},
        }
        chunks: list[str] = []
        last_data: dict[str, Any] = {}
        timeout = httpx.Timeout(connect=30.0, read=None, write=120.0, pool=60.0)
        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload, timeout=timeout
            ) as response:
                response.raise_for_status()
                import json as _json
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    row = _json.loads(line)
                    last_data = dict(row)
                    text = str((row.get("message") or {}).get("content") or "")
                    if text:
                        chunks.append(text)
                        if on_progress is not None:
                            on_progress(len(text), "Ollama is generating code")
                    if row.get("done"):
                        break
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError("Ollama is not reachable. Start Ollama and try again.") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise ProviderError(
                f"Ollama rejected the request ({exc.response.status_code}): {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        return ProviderResponse(
            text="".join(chunks),
            model=str(last_data.get("model") or model),
            raw=last_data,
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
        capabilities = await self.model_capabilities(model)
        if not capabilities.vision:
            raise ProviderConfigurationError(
                f"Ollama model '{model}' does not advertise vision support. "
                "Select a vision-capable model for screen analysis."
            )
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt, "images": [encoded]}
            ],
            "stream": False,
            "options": {"num_ctx": self._num_ctx},
        }
        data = await self._post_chat(payload)
        return ProviderResponse(
            text=str(data.get("message", {}).get("content", "") or ""),
            model=str(data.get("model") or model),
            raw=data,
        )

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            return dict(response.json())
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "Ollama is not reachable. Start Ollama and try again."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            raise ProviderError(
                f"Ollama rejected the request ({exc.response.status_code}): {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

    async def close(self) -> None:
        await self._client.aclose()
