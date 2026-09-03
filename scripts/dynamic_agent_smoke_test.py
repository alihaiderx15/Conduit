"""Run Phase 2's iterative agent against a controlled local webpage."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from conduit.agent import PlanExecutor
from conduit.browser import BrowserEngine
from conduit.dynamic_agent import DynamicAgentLoop
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider
from conduit.tools.builtin import registry


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    events = EventBus()

    async def show_event(event):
        if event.name.startswith("agent."):
            print(f"EVENT {event.name}: {dict(event.payload)}")

    events.subscribe("agent.*", show_event)

    if args.provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit("Set GEMINI_API_KEY before running the Gemini smoke test.")
        provider = GeminiProvider(api_key=key)
    else:
        provider = OllamaProvider()

    tool_executor = ToolExecutor(registry, event_bus=events)
    fixture = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "browser_test_page.html").as_uri()
    goal = (
        f"Open the local test page at {fixture}. Enter 'Conduit Phase 2 is working' into the input "
        "labeled 'Search query', click the Submit button, and finish only after the visible page text "
        "contains 'Submitted: Conduit Phase 2 is working'."
    )

    browser = BrowserEngine(event_bus=events, headless=args.headless)
    plan_executor = PlanExecutor(browser=browser, tools=tool_executor, event_bus=events, default_retries=0)
    agent = DynamicAgentLoop(
        provider=provider,
        model=args.model,
        executor=plan_executor,
        event_bus=events,
        max_iterations=10,
    )

    try:
        report = await agent.run(goal)
        print("\nDYNAMIC AGENT REPORT")
        for item in report.observations:
            marker = "OK" if item.success else "FAILED"
            print(f"  [{marker}] {item.action}: {item.message}")
        print(f"\nSTATUS: {report.status.value}")
        print(f"SUCCESS: {report.success}")
        print(f"MESSAGE: {report.final_message}")
        if report.pending_question:
            print(f"QUESTION: {report.pending_question}")
        if not report.success:
            raise SystemExit(1)
    finally:
        await browser.close()
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
