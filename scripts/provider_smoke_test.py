"""Manual provider test before any UI or tool executor is added."""

from __future__ import annotations

import argparse
import asyncio
import os

from conduit.core.models import ChatMessage, Role, ToolDefinition
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama"))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    if args.provider == "gemini":
        provider = GeminiProvider(os.environ.get("GEMINI_API_KEY", ""))
    else:
        provider = OllamaProvider()

    calculator = ToolDefinition(
        name="open_calculator",
        description="Open the Windows calculator application.",
        parameters={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )

    try:
        response = await provider.chat(
            [ChatMessage(Role.USER, "Open calculator")],
            model=args.model,
            tools=[calculator],
        )
        print("Text:", response.text)
        print("Tool calls:", response.tool_calls)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
