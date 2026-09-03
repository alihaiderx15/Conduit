"""Plan and execute a real Conduit browser goal."""

from __future__ import annotations

import argparse
import asyncio
import os

from conduit.agent import PlanExecutor
from conduit.browser import BrowserEngine
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.planning import TaskPlanner
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider
from conduit.tools.builtin import registry


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama"))
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--goal",
        default="Open the YouTube channel aceu and play their latest standard video upload",
    )
    args = parser.parse_args()

    provider = (
        GeminiProvider(os.environ.get("GEMINI_API_KEY", ""))
        if args.provider == "gemini"
        else OllamaProvider()
    )
    events = EventBus()

    async def show(event):
        if event.name.startswith(("plan.", "execution.")):
            print(f"EVENT {event.name}: {dict(event.payload)}")

    events.subscribe("*", show)
    browser = BrowserEngine(event_bus=events, headless=False, action_timeout_ms=15_000)
    planner = TaskPlanner(provider=provider, model=args.model, event_bus=events)
    executor = PlanExecutor(
        browser=browser,
        tools=ToolExecutor(registry, event_bus=events),
        event_bus=events,
    )

    try:
        plan = await planner.create_plan(args.goal)
        print(f"\nPLAN: {plan.summary}")
        for step in plan.steps:
            print(f"  {step.id}: {step.action} {dict(step.arguments)}")

        # A website-specific high-level action is safer and more reliable than blindly
        # executing selectors invented by a model. If the planner chose only low-level
        # actions, execute them as supplied; failures are reported step-by-step.
        report = await executor.execute(plan)
        print("\nEXECUTION REPORT")
        for item in report.results:
            print(f"  [{item.status.value.upper()}] {item.step.title}: {item.message}")
            if item.data:
                print(f"      {dict(item.data)}")
        print(f"\nSUCCESS: {report.success}")
        print(report.final_message)
    finally:
        await browser.close()
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
