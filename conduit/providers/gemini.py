"""Gemini provider using Google's current google-genai SDK."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence

from google import genai

from conduit.core.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderAuthenticationError,
    ProviderQuotaError,
)
from conduit.core.models import (
    ChatMessage,
    ProviderCapabilities,
    ProviderResponse,
    Role,
    ToolCall,
    ToolDefinition,
)
from conduit.core.schema import gemini_tool_dict
from conduit.providers.base import AIProvider
from conduit.core.prompting import with_core_prompt


class GeminiProvider(AIProvider):
    provider_id = "gemini"

    def __init__(self, api_key: str) -> None:
        if not api_key.strip():
            raise ProviderConfigurationError("Gemini API key is required.")
        self._client = genai.Client(api_key=api_key.strip())

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True, tools=True, vision=True, streaming=False)

    async def list_models(self) -> list[str]:
        try:
            models = await asyncio.to_thread(lambda: list(self._client.models.list()))
        except Exception as exc:  # SDK error types change between releases
            raise ProviderError(f"Gemini model discovery failed: {exc}") from exc

        names: list[str] = []
        for model in models:
            name = str(getattr(model, "name", ""))
            if name.startswith("models/"):
                name = name.removeprefix("models/")
            if name and "gemini" in name.lower():
                names.append(name)
        return sorted(set(names))

    @staticmethod
    def _build_input(messages: Sequence[ChatMessage]) -> str:
        # Interactions API currently accepts a simple input string. We preserve
        # roles explicitly so multi-turn context remains provider-neutral.
        lines: list[str] = []
        for message in messages:
            label = {
                Role.SYSTEM: "System",
                Role.USER: "User",
                Role.ASSISTANT: "Assistant",
                Role.TOOL: "Tool",
            }[message.role]
            lines.append(f"{label}: {message.content}")
        return "\n\n".join(lines)

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        tools: Sequence[ToolDefinition] = (),
    ) -> ProviderResponse:
        if not model.strip():
            raise ProviderConfigurationError("A Gemini model must be selected.")

        messages = with_core_prompt(messages)
        tool_payload = [
            gemini_tool_dict(tool.name, tool.description, tool.parameters)
            for tool in tools
        ]

        def request() -> Any:
            kwargs: dict[str, Any] = {
                "model": model,
                "input": self._build_input(messages),
            }
            if tool_payload:
                kwargs["tools"] = tool_payload
            return self._client.interactions.create(**kwargs)

        try:
            interaction = await asyncio.to_thread(request)
        except Exception as exc:
            message = str(exc)
            lowered = message.casefold()
            if any(token in lowered for token in ("api key", "api_key", "unauthenticated", "permission_denied", "401", "403")):
                raise ProviderAuthenticationError(f"Gemini credentials were rejected: {message}") from exc
            if any(token in lowered for token in ("resource_exhausted", "quota", "rate limit", "429")):
                raise ProviderQuotaError(f"Gemini quota is unavailable: {message}") from exc
            raise ProviderError(f"Gemini request failed: {message}") from exc

        calls: list[ToolCall] = []
        for step in getattr(interaction, "steps", ()) or ():
            if getattr(step, "type", None) != "function_call":
                continue
            arguments = getattr(step, "arguments", {}) or {}
            calls.append(
                ToolCall(
                    name=str(getattr(step, "name", "")),
                    arguments=dict(arguments),
                    call_id=str(getattr(step, "id", "")) or None,
                )
            )

        return ProviderResponse(
            text=str(getattr(interaction, "output_text", "") or ""),
            tool_calls=tuple(calls),
            model=model,
            raw=interaction,
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
            raise ProviderConfigurationError("A Gemini model must be selected.")

        def request_stream():
            pieces: list[str] = []
            last = None
            stream = self._client.models.generate_content_stream(
                model=model,
                contents=self._build_input(messages),
            )
            for chunk in stream:
                last = chunk
                text = str(getattr(chunk, "text", "") or "")
                if text:
                    pieces.append(text)
                    if on_progress is not None:
                        on_progress(len(text), "Gemini is generating code")
            return "".join(pieces), last

        try:
            text, raw = await asyncio.to_thread(request_stream)
        except Exception as exc:
            message = str(exc)
            lowered = message.casefold()
            if any(token in lowered for token in ("api key", "api_key", "unauthenticated", "permission_denied", "401", "403")):
                raise ProviderAuthenticationError(f"Gemini credentials were rejected: {message}") from exc
            if any(token in lowered for token in ("resource_exhausted", "quota", "rate limit", "429")):
                raise ProviderQuotaError(f"Gemini quota is unavailable: {message}") from exc
            raise ProviderError(f"Gemini streaming request failed: {message}") from exc

        return ProviderResponse(text=text, model=model, raw=raw)

    async def describe_image(
        self,
        image_path: Path,
        prompt: str,
        *,
        model: str,
    ) -> ProviderResponse:
        if not image_path.is_file():
            raise ProviderConfigurationError(f"Image not found: {image_path}")

        def request() -> Any:
            # generate_content remains the stable SDK path for byte-based
            # multimodal input and avoids uploading screenshots permanently.
            from google.genai import types

            image_part = types.Part.from_bytes(
                data=image_path.read_bytes(),
                mime_type=_mime_type(image_path),
            )
            return self._client.models.generate_content(
                model=model,
                contents=[prompt, image_part],
            )

        try:
            response = await asyncio.to_thread(request)
        except Exception as exc:
            message = str(exc)
            lowered = message.casefold()
            if any(token in lowered for token in ("api key", "api_key", "unauthenticated", "permission_denied", "401", "403")):
                raise ProviderAuthenticationError(f"Gemini credentials were rejected: {message}") from exc
            if any(token in lowered for token in ("resource_exhausted", "quota", "rate limit", "429")):
                raise ProviderQuotaError(f"Gemini quota is unavailable: {message}") from exc
            raise ProviderError(f"Gemini vision request failed: {message}") from exc
        return ProviderResponse(
            text=str(getattr(response, "text", "") or ""),
            model=model,
            raw=response,
        )


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
