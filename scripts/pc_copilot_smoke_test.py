"""End-to-end task-scoped approval smoke test using real Windows Notepad."""
from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

from conduit.actions import UnifiedActionRegistry, UnifiedActionRouter, register_default_actions
from conduit.agent import PlanExecutor
from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.browser import BrowserEngine
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.desktop import DesktopController
from conduit.dynamic_agent import DynamicAgentLoop
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.providers.base import AIProvider
from conduit.tools.builtin import registry


class ScriptedCopilotProvider(AIProvider):
    provider_id = "scripted-copilot"

    def __init__(self, note_text: str, target_path: str) -> None:
        self.responses = deque([
            '{"decision":"act","reason":"Open Notepad","action":"system.open_app","arguments":{"app":"notepad"}}',
            '{"decision":"act","reason":"Wait for Notepad","action":"system.wait","arguments":{"seconds":1.5}}',
            f'{{"decision":"act","reason":"Type the requested note","action":"desktop.type","arguments":{{"text":"{note_text}"}}}}',
            '{"decision":"act","reason":"Open Save As","action":"desktop.hotkey","arguments":{"keys":["ctrl","s"]}}',
            '{"decision":"act","reason":"Wait for Save As","action":"system.wait","arguments":{"seconds":1.0}}',
            f'{{"decision":"act","reason":"Enter the approved file path","action":"desktop.type","arguments":{{"text":"{target_path.replace(chr(92), chr(92)*2)}"}}}}',
            '{"decision":"act","reason":"Confirm save","action":"desktop.press","arguments":{"key":"enter"}}',
            '{"decision":"act","reason":"Wait for disk write","action":"system.wait","arguments":{"seconds":1.0}}',
            f'{{"decision":"act","reason":"Verify the saved file","action":"files.exists","arguments":{{"path":"{target_path.replace(chr(92), chr(92)*2)}"}},"save_as":{{"saved":"data.exists"}}}}',
            '{"decision":"finish","reason":"The filesystem verification returned true","message":"The Notepad file was saved and verified."}',
        ])

    @property
    def capabilities(self):
        return ProviderCapabilities(chat=True)

    async def list_models(self):
        return ["scripted"]

    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(text=self.responses.popleft())


async def main() -> None:
    if __import__('sys').platform != 'win32':
        raise SystemExit('This smoke test requires Windows.')

    root = Path(__file__).resolve().parents[1]
    output_dir = root / "data" / "pc-copilot-smoke"
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "conduit-test.txt"
    target.unlink(missing_ok=True)
    note_text = "Conduit is working"

    actions = register_default_actions(UnifiedActionRegistry(registry))
    allowed = frozenset({
        "desktop.type", "desktop.hotkey", "desktop.press"
    })
    scope = ApprovalScope(
        goal=f"Open Notepad, type {note_text!r}, save to {target}, and verify the file.",
        allowed_actions=allowed,
        allowed_path_roots=(output_dir,),
        max_confirmed_actions=6,
        argument_constraints={
            "desktop.type": {"text": (note_text, str(target))},
            "desktop.hotkey": {"keys": (("ctrl", "s"),)},
            "desktop.press": {"key": ("enter",)},
        },
    )
    print("\nTASK APPROVAL REQUEST\n")
    print(scope.describe())
    answer = input("\nType YES to approve this exact task scope: ").strip()
    if answer != "YES":
        raise SystemExit("Task was not approved.")
    approval = TaskApprovalSession(scope)
    approval.approve()

    events = EventBus()
    async def show(event):
        if event.name.startswith("execution.confirmation") or event.name.startswith("agent.observation"):
            print(f"EVENT {event.name}: {dict(event.payload)}")
    events.subscribe("execution.confirmation.*", show)
    events.subscribe("agent.observation.*", show)

    browser = BrowserEngine(event_bus=events, headless=True)
    tools = ToolExecutor(registry, event_bus=events)
    router = UnifiedActionRouter(browser=browser, tools=tools, desktop=DesktopController(event_bus=events))
    executor = PlanExecutor(
        browser=browser,
        tools=tools,
        event_bus=events,
        default_retries=0,
        action_router=router,
        approval_session=approval,
    )
    agent = DynamicAgentLoop(
        provider=ScriptedCopilotProvider(note_text, str(target)),
        model="scripted",
        executor=executor,
        capabilities=actions.planning_capabilities(),
        event_bus=events,
        max_iterations=12,
    )

    try:
        report = await agent.run(scope.goal, initial_variables={"target_path": str(target)})
    finally:
        await browser.close()

    print("\nPC COPILOT REPORT")
    for obs in report.observations:
        print(f"  [{'OK' if obs.success else 'FAILED'}] {obs.action}: {obs.message}")
    print(f"SUCCESS: {report.success}")
    print(f"FILE: {target}")
    if not report.success or not target.exists() or note_text not in target.read_text(encoding='utf-8', errors='replace'):
        raise SystemExit("The end-to-end PC Copilot test did not verify the saved file.")
    print("TASK-SCOPED PC COPILOT SMOKE TEST: PASS")


if __name__ == "__main__":
    asyncio.run(main())
