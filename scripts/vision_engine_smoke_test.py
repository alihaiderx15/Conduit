"""Manual Module 6 smoke test: structured locate and optional approved click."""
from __future__ import annotations

import argparse
import asyncio
import os

from conduit.desktop import DesktopController
from conduit.observer import DesktopObserver, ObserveActWorkflow
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=["gemini", "ollama"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--target", required=True, help="Visible element to locate, e.g. 'Notepad text area'")
    parser.add_argument("--click", action="store_true", help="Offer an explicit confirmation before clicking")
    args = parser.parse_args()

    if args.provider == "gemini":
        key = os.getenv("GEMINI_API_KEY", "")
        if not key:
            raise SystemExit("Set GEMINI_API_KEY first.")
        provider = GeminiProvider(key)
    else:
        provider = OllamaProvider()
        capabilities = await provider.model_capabilities(args.model)
        print(f"Model capabilities: {capabilities}")
        if not capabilities.vision:
            print(f"Screen analysis skipped: Ollama model '{args.model}' does not support vision.")
            return

    observer = DesktopObserver(provider, model=args.model)
    workflow = ObserveActWorkflow(observer, DesktopController())
    located = await workflow.locate(args.target)
    element = located.element
    print(f"Application: {located.analysis.application}")
    print(f"Summary: {located.analysis.summary}")
    print(f"Located: id={element.element_id!r}, label={element.label!r}, role={element.role!r}")
    print(f"Bounds: {element.bounds}; center={element.center}; confidence={element.confidence:.2f}")

    if not args.click:
        print("Locate-only test complete. No desktop action was performed.")
        return

    answer = input(f"Click '{element.label}' at {element.center}? Type YES to approve: ").strip()
    if answer != "YES":
        print("Cancelled. No desktop action was performed.")
        return
    result = await workflow.click_and_verify(located, approved=True)
    print(result.action)
    print(f"Visible change detected: {result.changed}")
    print(f"Verification: {result.verification_summary}")


if __name__ == "__main__":
    asyncio.run(main())
