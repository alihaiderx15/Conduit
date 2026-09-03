"""Manual smoke test for Module 7B."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from conduit.browser import BrowserEngine, BrowserTarget, TargetKind
from conduit.events import EventBus


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("local", "live"), nargs="?", default="local")
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    events = EventBus()
    events.subscribe("browser.*", lambda e: print(f"EVENT {e.name}: {dict(e.payload)}"))
    engine = BrowserEngine(event_bus=events, headless=args.headless)

    async with engine:
        if args.mode == "local":
            page = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "browser_test_page.html").as_uri()
            await engine.goto(page)
            field = BrowserTarget(TargetKind.LABEL, "Search query")
            button = BrowserTarget(TargetKind.ROLE, "button", name="Submit")
            await engine.fill(field, "Conduit semantic browser control")
            await engine.click(button)
            await engine.scroll(delta_y=900)
            state = await engine.state()
            print("\nTITLE:", state.title)
            print("URL:", state.url)
            print("VISIBLE TEXT:\n", state.visible_text)
            print("\nLocal browser smoke test passed.")
        else:
            await engine.goto("https://example.com")
            state = await engine.state()
            print("\nTITLE:", state.title)
            print("URL:", state.url)
            print("VISIBLE TEXT:\n", state.visible_text[:1000])
            print("\nLive browser smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
