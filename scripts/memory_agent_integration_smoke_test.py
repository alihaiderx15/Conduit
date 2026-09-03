"""Verify persistent memory retrieval, agent injection, and controlled writing."""

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
from conduit.memory import AgentMemoryBridge, MemoryCategory, MemoryManager, MemoryWriteMode
from conduit.providers.base import AIProvider
from conduit.tools.builtin import registry


class MemoryAwareScriptedProvider(AIProvider):
    provider_id = "memory-aware-scripted"

    def __init__(self, fixture_url: str, remembered_phrase: str) -> None:
        self.fixture_url = fixture_url
        self.remembered_phrase = remembered_phrase
        self.responses = deque([
            '{"decision":"act","reason":"Start the browser","action":"browser.start","arguments":{}}',
            '{"decision":"act","reason":"Open the controlled page","action":"browser.goto",'
            f'"arguments":{{"url":"{fixture_url}"}}}}',
            '{"decision":"act","reason":"Use the remembered preference","action":"browser.fill",'
            f'"arguments":{{"kind":"label","value":"Search query","text":"{remembered_phrase}"}}}}',
            '{"decision":"act","reason":"Submit the remembered value","action":"browser.click",'
            '"arguments":{"kind":"role","value":"button","name":"Submit"}}',
            '{"decision":"act","reason":"Read the result as evidence","action":"browser.read_page","arguments":{}}',
            '{"decision":"finish","reason":"The page proves the remembered phrase was submitted",'
            '"message":"Persistent memory influenced the agent successfully.",'
            '"memory_proposals":[{"key":"memory_agent_smoke_status","value":"passed",'
            '"category":"fact","importance":0.8,"reason":"The integration was verified on the local test page"}]}',
        ])
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(chat=True)

    async def list_models(self) -> list[str]:
        return ["scripted"]

    async def chat(self, messages, *, model, tools=()):
        prompt = messages[-1].content
        if self.remembered_phrase not in prompt:
            raise RuntimeError("The remembered phrase was not injected into the agent prompt.")
        self.calls += 1
        return ProviderResponse(text=self.responses.popleft())


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = data_dir / "conduit-memory-agent-smoke.db"
    if db_path.exists():
        db_path.unlink()

    remembered_phrase = "Remembered by Conduit"
    fixture_url = (root / "tests" / "fixtures" / "browser_test_page.html").as_uri()
    events = EventBus()

    async def show_event(event) -> None:
        if event.name.startswith("memory.") or event.name.startswith("agent.memory"):
            print(f"EVENT {event.name}: {dict(event.payload)}")

    events.subscribe("memory.*", show_event)
    events.subscribe("agent.memory.*", show_event)

    memory = MemoryManager(db_path, event_bus=events)
    memory.remember(
        "preferred_test_phrase",
        remembered_phrase,
        category=MemoryCategory.PREFERENCE,
        importance=1.0,
        source="smoke_test",
    )
    bridge = AgentMemoryBridge(
        memory,
        write_mode=MemoryWriteMode.AUTO_SAFE,
        event_bus=events,
    )
    browser = BrowserEngine(event_bus=events, headless=False)
    executor = PlanExecutor(
        browser=browser,
        tools=ToolExecutor(registry, event_bus=events),
        event_bus=events,
        default_retries=0,
    )
    agent = DynamicAgentLoop(
        provider=MemoryAwareScriptedProvider(fixture_url, remembered_phrase),
        model="scripted",
        executor=executor,
        event_bus=events,
        memory_bridge=bridge,
        max_iterations=8,
    )

    try:
        report = await agent.run("Submit my preferred test phrase on the controlled page.")
        print("\nRELEVANT MEMORIES")
        for item in report.relevant_memories:
            print(f"  {item}")
        print("\nMEMORY PROPOSALS")
        for item in report.memory_proposal_results:
            print(f"  {item.proposal.key}: saved={item.saved} ({item.reason})")
        print(f"\nSTATUS: {report.status.value}")
        print(f"SUCCESS: {report.success}")

        visible_text = str(report.variables.get("last", {}).get("data", {}).get("visible_text", ""))
        expected = f"Submitted: {remembered_phrase}"
        if not report.success or expected not in visible_text:
            raise SystemExit(f"Expected page evidence {expected!r}, got {visible_text!r}")
    finally:
        await browser.close()
        memory.close()

    # Reopen to prove the model-proposed memory was persisted safely.
    reopened = MemoryManager(db_path)
    saved = reopened.repository.get_memory(MemoryCategory.FACT, "memory_agent_smoke_status")
    reopened.close()
    if saved is None or saved.value != "passed":
        raise SystemExit("The safe model-proposed memory did not persist across restart.")
    print("PERSISTENCE VERIFIED: memory_agent_smoke_status=passed")
    print("MODULE 9.1 MEMORY-AGENT INTEGRATION: PASS")


if __name__ == "__main__":
    asyncio.run(main())
