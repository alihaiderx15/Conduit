"""Run a natural-language General PC Agent v1 benchmark with Gemini or Ollama."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    if args.provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit("Set GEMINI_API_KEY before running this test.")
        provider = GeminiProvider(api_key=key)
    else:
        provider = OllamaProvider()

    root = Path(__file__).resolve().parents[1]
    sandbox = (root / "data" / "general-pc-smoke").resolve()
    sandbox.mkdir(parents=True, exist_ok=True)
    target = sandbox / "general-pc-agent.txt"
    target.unlink(missing_ok=True)
    expected = "Conduit General PC Agent v1 is working"

    goal = (
        f"Create a UTF-8 text file at the exact path {target} containing exactly {expected!r}. "
        "Verify that the file exists, read it back to verify the exact contents, then open the file "
        "in its default Windows application. Finish only after the filesystem evidence proves the goal."
    )
    scope = ApprovalScope(
        goal=goal,
        allowed_actions=frozenset({"files.write_text"}),
        allowed_path_roots=(sandbox,),
        max_confirmed_actions=2,
        argument_constraints={"files.write_text": {"path": (str(target),), "text": (expected,)}},
    )
    print("\nGENERAL PC AGENT APPROVAL REQUEST\n")
    print(scope.describe())
    if input("\nType YES to approve this exact write scope: ").strip() != "YES":
        raise SystemExit("Task was not approved.")
    approval = TaskApprovalSession(scope); approval.approve()

    events = EventBus()
    async def show(event):
        if event.name.startswith(("general_pc.", "agent.decision", "agent.observation", "agent.recovery", "execution.confirmation")):
            print(f"EVENT {event.name}: {dict(event.payload)}")
    events.subscribe("*", show)

    agent = await GeneralPCAgent.create(
        provider=provider,
        model=args.model,
        config=GeneralPCAgentConfig(headless_browser=args.headless, max_iterations=14),
        event_bus=events,
        approval_session=approval,
    )
    try:
        report = await agent.run(goal, initial_variables={"target_path": str(target), "expected_text": expected})
    finally:
        await agent.close()

    print("\nGENERAL PC AGENT REPORT")
    for obs in report.observations:
        print(f"  [{'OK' if obs.success else 'FAILED'}] {obs.action}: {obs.message}")
    print(f"STATUS: {report.status.value}")
    print(f"SUCCESS: {report.success}")
    print(f"MESSAGE: {report.final_message}")

    verified = target.exists() and target.read_text(encoding="utf-8", errors="replace") == expected
    if not report.success or not verified:
        raise SystemExit("General PC Agent v1 did not verify the benchmark goal.")
    print("GENERAL PC AGENT V1 SMOKE TEST: PASS")


if __name__ == "__main__":
    asyncio.run(main())
