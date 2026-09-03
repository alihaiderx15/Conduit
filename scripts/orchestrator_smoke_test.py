"""Interactive terminal smoke test for the complete Conduit backend loop."""

from __future__ import annotations

import argparse
import asyncio
import os

from conduit.assistant import AssistantOrchestrator, TurnStatus
from conduit.execution.executor import ToolExecutor
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider
from conduit.tools.builtin import registry


def build_provider(name: str):
    if name == "ollama":
        return OllamaProvider()
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise SystemExit("Set GEMINI_API_KEY before running the Gemini test.")
    return GeminiProvider(key)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=["ollama", "gemini"])
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    provider = build_provider(args.provider)
    orchestrator = AssistantOrchestrator(
        provider=provider,
        model=args.model,
        registry=registry,
        executor=ToolExecutor(registry),
    )

    print("Conduit terminal smoke test. Type 'exit' to quit.")
    print("Try: Open calculator")
    print("Try: Create a folder named Conduit Test")
    try:
        while True:
            text = input("\nYou: ").strip()
            if text.casefold() in {"exit", "quit"}:
                break
            turn = await orchestrator.submit(text)
            print(f"Conduit: {turn.message}")
            if turn.tool_results:
                for result in turn.tool_results:
                    print(f"  ToolResult: {result}")
            if turn.status is TurnStatus.AWAITING_CONFIRMATION:
                print("  Confirmation is pending.")
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
