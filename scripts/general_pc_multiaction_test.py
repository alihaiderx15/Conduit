"""Real natural-language Windows multi-action benchmark for General PC Agent v1.1."""
from __future__ import annotations
import argparse, asyncio, os
from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider
from conduit.providers.console_recovery import ConsoleProviderRecovery

TEXT = "Conduit General PC Agent v1.1"

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("provider", choices=("gemini","ollama"))
    ap.add_argument("--model", required=True)
    args=ap.parse_args()
    if args.provider=="gemini":
        key=os.environ.get("GEMINI_API_KEY","").strip()
        if not key: raise SystemExit("Set GEMINI_API_KEY first.")
        provider=GeminiProvider(api_key=key)
    else:
        provider=OllamaProvider()

    goal=(
        f"Open Notepad and type exactly {TEXT!r}. Select all of that text and copy it using the keyboard. "
        "Read the Windows clipboard to verify it contains the exact text. Then minimize the Notepad window "
        "and verify Notepad is still running. Use available structured system/clipboard actions for verification. "
        "Do not save or create a file. Finish only after the clipboard and running-process evidence prove the goal."
    )
    scope=ApprovalScope(
        goal=goal,
        allowed_actions=frozenset({"desktop.type","desktop.hotkey"}),
        max_confirmed_actions=8,
        argument_constraints={
            "desktop.type":{"text":(TEXT,)},
            "desktop.hotkey":{"keys":(("ctrl","a"),("ctrl","c"))},
        },
    )
    print("\nMULTI-ACTION WINDOWS APPROVAL\n")
    print(scope.describe())
    if input("\nType YES to approve keyboard input for this task: ").strip()!="YES":
        raise SystemExit("Not approved.")
    approval=TaskApprovalSession(scope); approval.approve()

    events=EventBus()
    async def show(e):
        if e.name.startswith(("general_pc.","agent.","execution.confirmation")):
            print(f"EVENT {e.name}: {dict(e.payload)}")
    events.subscribe("*",show)

    agent=await GeneralPCAgent.create(
        provider=provider, model=args.model,
        config=GeneralPCAgentConfig(max_iterations=16),
        event_bus=events,
        approval_session=approval,
        provider_recovery_handler=ConsoleProviderRecovery(
            ollama_model="qwen3:8b",
            gemini_model=args.model if args.provider == "gemini" else "gemini-flash-latest",
        ),
    )
    try:
        report=await agent.run(goal, initial_variables={"expected_text":TEXT})
    finally:
        await agent.close()

    actions=[o.action for o in report.observations if o.success]
    clip=[o for o in report.observations if o.action=="clipboard.read" and o.success]
    clipboard_ok=any(o.data.get("text","").strip()==TEXT for o in clip)
    minimized=any(o.action=="system.window_state" and o.success and o.data.get("state")=="minimize" for o in report.observations)
    process_checked=any(o.action=="system.list_processes" and o.success for o in report.observations)

    print("\nMULTI-ACTION REPORT")
    for o in report.observations:
        print(f"  [{'OK' if o.success else 'FAILED'}] {o.action}: {o.message}")
    print("STATUS:",report.status.value)
    print("SUCCESS:",report.success)
    print("CLIPBOARD VERIFIED:",clipboard_ok)
    print("MINIMIZE VERIFIED:",minimized)
    print("PROCESS CHECKED:",process_checked)
    if not (report.success and clipboard_ok and minimized and process_checked):
        raise SystemExit("Multi-action benchmark did not prove every required outcome.")
    print("GENERAL PC AGENT V1.1 MULTI-ACTION TEST: PASS")

if __name__=="__main__":
    asyncio.run(main())
