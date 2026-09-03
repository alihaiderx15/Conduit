"""Prove that a dynamic agent can capture an action result and reuse it later."""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

from conduit.agent import PlanExecutor
from conduit.browser import BrowserEngine
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.dynamic_agent import DynamicAgentLoop
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.providers.base import AIProvider
from conduit.tools.builtin import registry


class ScriptedProvider(AIProvider):
    """Deterministic provider used only for this architecture smoke test."""

    provider_id = "scripted-context-smoke"

    def __init__(self) -> None:
        self._responses = deque(
            ProviderResponse(text=item)
            for item in (
                '{"decision":"act","reason":"Start the managed browser","action":"browser.start","arguments":{}}',
                '{"decision":"act","reason":"Open the controlled page","action":"browser.goto",'
                '"arguments":{"url":"{{fixture_url}}"}}',
                '{"decision":"act","reason":"Read and retain the page title","action":"browser.read_page",'
                '"arguments":{},"save_as":{"discovered_title":"data.title","discovered_url":"data.url"}}',
                '{"decision":"act","reason":"Reuse the captured title as input text","action":"browser.fill",'
                '"arguments":{"kind":"label","value":"Search query","text":"{{discovered_title}}"}}',
                '{"decision":"act","reason":"Submit the reused value","action":"browser.click",'
                '"arguments":{"kind":"role","value":"button","name":"Submit"}}',
                '{"decision":"act","reason":"Read the result for evidence","action":"browser.read_page","arguments":{}}',
                '{"decision":"finish","reason":"The submitted result contains the captured page title",'
                '"message":"Captured and reused the discovered page title successfully."}',
            )
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True, tools=False, vision=False, streaming=False)

    async def list_models(self) -> list[str]:
        return ["scripted"]

    async def chat(self, messages, *, model, tools=()):
        return self._responses.popleft()


async def main() -> None:
    events = EventBus()

    async def show_event(event) -> None:
        if event.name in {"agent.variables.captured", "agent.variable.resolution_failed"}:
            print(f"EVENT {event.name}: {dict(event.payload)}")

    events.subscribe("agent.*", show_event)

    fixture_url = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "browser_test_page.html").as_uri()
    browser = BrowserEngine(event_bus=events, headless=False)
    executor = PlanExecutor(
        browser=browser,
        tools=ToolExecutor(registry, event_bus=events),
        event_bus=events,
        default_retries=0,
    )
    agent = DynamicAgentLoop(
        provider=ScriptedProvider(),
        model="scripted",
        executor=executor,
        event_bus=events,
        max_iterations=9,
    )

    try:
        report = await agent.run(
            "Capture the current page title, reuse it in the Search query field, and submit it.",
            initial_variables={"fixture_url": fixture_url},
        )
        print("\nCONTEXT VARIABLES")
        print(f"  fixture_url: {report.variables.get('fixture_url')}")
        print(f"  discovered_title: {report.variables.get('discovered_title')}")
        print(f"  discovered_url: {report.variables.get('discovered_url')}")
        print(f"\nSTATUS: {report.status.value}")
        print(f"SUCCESS: {report.success}")
        print(f"MESSAGE: {report.final_message}")

        final_text = str(report.variables.get("last", {}).get("data", {}).get("visible_text", ""))
        expected = "Submitted: Conduit Browser Test"
        if not report.success or expected not in final_text:
            raise SystemExit(f"Context reuse smoke test failed. Expected visible text: {expected!r}")
        print(f"VERIFIED: {expected}")
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
