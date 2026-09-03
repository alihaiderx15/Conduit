"""Provider-neutral desktop observation service."""

from __future__ import annotations

import asyncio
from pathlib import Path

from conduit.core.errors import ProviderConfigurationError
from conduit.core.models import ChatMessage, Role
from conduit.observer.capture import DesktopCaptureService
from conduit.observer.models import ScreenAnalysis, ScreenCapture, StructuredScreenAnalysis
from conduit.observer.parser import parse_structured_screen_analysis, ScreenAnalysisParseError
from conduit.providers.base import AIProvider


DEFAULT_SCREEN_PROMPT = (
    "Describe only what is visibly present on this desktop screenshot. "
    "Mention the active application, important visible text, dialogs, buttons, "
    "and anything that may require the user's attention. Do not guess hidden state."
)

STRUCTURED_SCREEN_PROMPT = """
Analyze this desktop screenshot and return ONLY valid JSON with this exact structure:
{
  "application": "visible active application name",
  "summary": "brief factual summary of visible state",
  "elements": [
    {
      "id": "short_stable_id",
      "label": "human-readable visible label",
      "role": "button|textbox|link|checkbox|radio|menuitem|tab|combobox|slider|listitem|text|image|unknown",
      "bounds": {"x": 0, "y": 0, "width": 1, "height": 1},
      "confidence": 0.0,
      "text": "visible text if any",
      "enabled": true,
      "visible": true
    }
  ]
}
Coordinates must be integer pixels relative to the full screenshot. Include only clearly visible elements.
Never invent hidden elements. Never include markdown or commentary outside the JSON.
""".strip()


class DesktopObserver:
    """Capture the desktop and ask the selected provider to inspect it."""

    def __init__(
        self,
        provider: AIProvider,
        *,
        model: str,
        capture_service: DesktopCaptureService | None = None,
    ) -> None:
        if not model.strip():
            raise ProviderConfigurationError("A vision model must be selected.")
        self._provider = provider
        self._model = model
        self._capture_service = capture_service or DesktopCaptureService()

    async def capture(self, destination: Path | None = None) -> ScreenCapture:
        return await asyncio.to_thread(self._capture_service.capture, destination)

    def _require_vision(self) -> None:
        if not self._provider.capabilities.vision:
            raise ProviderConfigurationError(
                f"Provider '{self._provider.provider_id}' does not support images."
            )

    async def analyze(
        self,
        prompt: str = DEFAULT_SCREEN_PROMPT,
        *,
        capture: ScreenCapture | None = None,
    ) -> ScreenAnalysis:
        self._require_vision()
        capture = capture or await self.capture()
        response = await self._provider.describe_image(capture.image_path, prompt, model=self._model)
        return ScreenAnalysis(
            capture=capture,
            prompt=prompt,
            description=response.text.strip(),
            provider_id=self._provider.provider_id,
            model=response.model or self._model,
        )

    async def analyze_structured(
        self,
        goal: str = "Identify the important visible controls and information.",
        *,
        capture: ScreenCapture | None = None,
    ) -> StructuredScreenAnalysis:
        """Return validated structured perception instead of free-form prose."""
        self._require_vision()
        capture = capture or await self.capture()
        prompt = f"{STRUCTURED_SCREEN_PROMPT}\n\nUser goal: {goal.strip()}"
        response = await self._provider.describe_image(
            capture.image_path,
            prompt,
            model=self._model,
        )
        try:
            return parse_structured_screen_analysis(
                response.text,
                capture=capture,
                provider_id=self._provider.provider_id,
                model=response.model or self._model,
            )
        except ScreenAnalysisParseError as first_error:
            # Local multimodal models can visually understand the screen yet
            # occasionally emit almost-JSON. Ask the SAME model to repair only
            # the serialization, without changing the visual claims.
            repair_prompt = (
                "Repair the following malformed structured-screen response into "
                "STRICT VALID JSON only. Preserve the same application, summary, "
                "elements, text, roles, confidence values and pixel coordinates. "
                "Do not add new elements or facts. Use double-quoted JSON keys and "
                "strings, lowercase true/false, and no markdown.\n\n"
                f"MALFORMED RESPONSE:\n{response.text}"
            )
            repaired = await self._provider.chat(
                [ChatMessage(Role.USER, repair_prompt)],
                model=self._model,
            )
            try:
                return parse_structured_screen_analysis(
                    repaired.text,
                    capture=capture,
                    provider_id=self._provider.provider_id,
                    model=repaired.model or self._model,
                )
            except ScreenAnalysisParseError:
                # One final image retry is allowed because a fresh generation
                # often resolves formatting mistakes on local vision models.
                retry_prompt = (
                    f"{STRUCTURED_SCREEN_PROMPT}\n\n"
                    "IMPORTANT: your previous answer was rejected because it was "
                    "not valid JSON. Return one strict JSON object only.\n\n"
                    f"User goal: {goal.strip()}"
                )
                retry = await self._provider.describe_image(
                    capture.image_path,
                    retry_prompt,
                    model=self._model,
                )
                try:
                    return parse_structured_screen_analysis(
                        retry.text,
                        capture=capture,
                        provider_id=self._provider.provider_id,
                        model=retry.model or self._model,
                    )
                except ScreenAnalysisParseError as final_error:
                    raise ScreenAnalysisParseError(
                        f"{final_error}. Structured vision repair also failed."
                    ) from first_error
