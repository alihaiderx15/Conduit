"""Interactive provider recovery for paused Conduit tasks."""
from __future__ import annotations

import asyncio
import re

from conduit.core.errors import ProviderError, ProviderQuotaError
from conduit.core.models import ChatMessage, Role
from .base import AIProvider
from .console_input import masked_input
from .recovery import ProviderReplacement


def _choose_openai_model(models: list[str]) -> str:
    usable = [
        m for m in models
        if m.startswith("gpt-")
        and not any(x in m for x in (
            "realtime", "audio", "transcribe", "tts", "image",
            "search-preview", "chatgpt",
        ))
    ]
    preferences = (
        "gpt-5-mini", "gpt-5.1-mini", "gpt-5.1", "gpt-5",
        "gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o",
    )
    for preferred in preferences:
        if preferred in usable:
            return preferred
    return usable[0] if usable else (models[0] if models else "")


def _choose_grok_model(models: list[str]) -> str:
    usable = [
        m for m in models
        if m.casefold().startswith("grok")
        and not any(x in m.casefold() for x in ("image", "video", "imagine"))
    ]
    preferences = (
        "grok-4.6", "grok-4.1-fast", "grok-4-fast",
        "grok-4", "grok-3-mini", "grok-3",
    )
    for preferred in preferences:
        if preferred in usable:
            return preferred
    return usable[0] if usable else (models[0] if models else "")


async def _select_ollama_model(candidate) -> str:
    models = await candidate.list_models()
    if not models:
        raise RuntimeError("Ollama is running but no local models are installed.")
    print("\nInstalled Ollama models:")
    for i, model in enumerate(models, 1):
        try:
            caps = await candidate.model_capabilities(model)
            tags = []
            if caps.vision:
                tags.append("vision")
            if caps.tools:
                tags.append("tools")
            suffix = " [" + " + ".join(tags) + "]" if tags else ""
        except Exception:
            suffix = ""
        print(f" [{i}] {model}{suffix}")
    while True:
        raw = (await asyncio.to_thread(input, "Select Ollama model number: ")).strip()
        if raw.isdigit() and 1 <= int(raw) <= len(models):
            return models[int(raw)-1]
        print("Choose one of the displayed model numbers.")


class ConsoleProviderRecovery:
    def __init__(
        self,
        *,
        ollama_model: str = "qwen3:8b",
        gemini_model: str = "gemini-flash-latest",
    ) -> None:
        self.ollama_model = ollama_model
        self.gemini_model = gemini_model

    async def __call__(self, error: ProviderError, current: AIProvider, current_model: str):
        print("\nConduit paused because the AI provider became unavailable.")
        print(f"Reason: {error}")
        print("Completed task state is preserved.")

        retry_seconds = _retry_after_seconds(str(error))
        while True:
            options: list[tuple[str, str]] = []
            if isinstance(error, ProviderQuotaError):
                options.append(("wait", f"Wait {retry_seconds:.0f} seconds and retry" if retry_seconds else "Wait briefly and retry"))

            if current.provider_id == "gemini":
                options.append(("new_gemini", "Enter a new Gemini API key"))
            elif current.provider_id == "openai":
                options.append(("new_openai", "Enter a new OpenAI API key"))

            if current.provider_id != "gemini":
                options.append(("gemini", "Switch to Gemini"))
            if current.provider_id != "openai":
                options.append(("openai", "Switch to OpenAI"))
            if current.provider_id != "ollama":
                options.append(("ollama", "Switch to Ollama"))
            options.append(("cancel", "Cancel / pause task"))

            for i, (_, label) in enumerate(options, 1):
                print(f"[{i}] {label}")
            raw = (await asyncio.to_thread(input, f"Choose 1-{len(options)}: ")).strip()
            if not raw.isdigit() or not 1 <= int(raw) <= len(options):
                print("Choose one of the displayed options.")
                continue
            action = options[int(raw)-1][0]

            if action == "wait":
                delay = retry_seconds or 45.0
                print(f"Waiting {delay:.0f} seconds. The current task remains paused.")
                await asyncio.sleep(max(1.0, delay))
                return ProviderReplacement(current, current_model, "User waited and retried the provider.")

            if action in {"new_gemini", "gemini"}:
                key = await asyncio.to_thread(masked_input, "Gemini API key: ")
                from .gemini import GeminiProvider
                candidate = GeminiProvider(key)
                try:
                    models = await candidate.list_models()
                    model = self.gemini_model if self.gemini_model in models else next(
                        (m for m in models if "flash" in m.casefold()), models[0]
                    )
                    await candidate.chat([ChatMessage(Role.USER, "Reply with OK only.")], model=model)
                    return ProviderReplacement(candidate, model, "Connected to Gemini with validated credentials.")
                except Exception as exc:
                    await candidate.close()
                    print(f"Gemini validation failed: {exc}")
                    continue

            if action in {"new_openai", "openai"}:
                key = await asyncio.to_thread(masked_input, "OpenAI API key: ")
                from .openai import OpenAIProvider
                candidate = OpenAIProvider(key)
                try:
                    models = await candidate.list_models()
                    model = _choose_openai_model(models)
                    if not model:
                        raise RuntimeError("No usable OpenAI model was available to this key.")
                    await candidate.chat([ChatMessage(Role.USER, "Reply with OK only.")], model=model)
                    return ProviderReplacement(candidate, model, "Connected to OpenAI with validated credentials.")
                except Exception as exc:
                    await candidate.close()
                    print(f"OpenAI validation failed: {exc}")
                    continue

            if action == "ollama":
                from .ollama import OllamaProvider
                candidate = OllamaProvider()
                try:
                    model = await _select_ollama_model(candidate)
                    return ProviderReplacement(candidate, model, "User selected an installed Ollama model.")
                except Exception as exc:
                    await candidate.close()
                    print(f"Ollama selection failed: {exc}")
                    continue

            return None


def _retry_after_seconds(message: str) -> float | None:
    match = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s?", message, re.I)
    if match:
        return max(1.0, float(match.group(1)))
    match = re.search(r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*seconds?", message, re.I)
    return max(1.0, float(match.group(1))) if match else None
