"""Capture and optionally analyze the current Windows desktop."""

from __future__ import annotations

import argparse
import asyncio
import os

from conduit.observer import DesktopCaptureService, DesktopObserver
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("capture", "gemini", "ollama"))
    parser.add_argument("--model")
    parser.add_argument(
        "--prompt",
        default="Describe the visible desktop and identify the active application.",
    )
    args = parser.parse_args()

    if args.provider == "capture":
        capture = await asyncio.to_thread(DesktopCaptureService().capture)
        print(f"Screenshot: {capture.image_path}")
        print(f"Size: {capture.width}x{capture.height}")
        print(f"Active window: {capture.active_window}")
        return

    if not args.model:
        parser.error("--model is required for analysis")

    if args.provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        provider = GeminiProvider(key)
    else:
        provider = OllamaProvider()

    try:
        capabilities = await provider.model_capabilities(args.model)
        print(f"Model capabilities: {capabilities}")
        observer = DesktopObserver(provider, model=args.model)
        analysis = await observer.analyze(args.prompt)
        print(f"Screenshot: {analysis.capture.image_path}")
        print(f"Active window: {analysis.capture.active_window}")
        print("Analysis:")
        print(analysis.description)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
