"""Direct smoke test for the reusable YouTube capability."""

from __future__ import annotations

import argparse
import asyncio

from conduit.browser import BrowserEngine
from conduit.capabilities import YouTubeAgent
from conduit.events import EventBus


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="aceu")
    args = parser.parse_args()

    events = EventBus()
    async def show(event):
        if event.name.startswith("browser."):
            print(f"EVENT {event.name}: {dict(event.payload)}")
    events.subscribe("browser.*", show)

    browser = BrowserEngine(event_bus=events, headless=False, action_timeout_ms=15_000)
    try:
        result = await YouTubeAgent(browser, event_bus=events).play_latest_upload(args.channel)
        print("\nYOUTUBE RESULT")
        print(f"Channel: {result.channel}")
        print(f"Title: {result.video_title}")
        print(f"URL: {result.video_url}")
        print(f"Verified: {result.verified}")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
