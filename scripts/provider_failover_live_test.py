"""Live Gemini -> Ollama mid-task failover benchmark.

Gemini is allowed to make the first reasoning decision. Before its second decision,
a controlled recoverable auth failure is injected. The same AgentContext is then
continued by Ollama. The benchmark fails if the already-completed write is repeated.
"""
from __future__ import annotations
import argparse, asyncio, os
from pathlib import Path
from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider
from conduit.providers.fault_injection import FailAfterNProvider
from conduit.providers.recovery import ProviderReplacement

async def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--gemini-model", default="gemini-flash-latest")
    ap.add_argument("--ollama-model", default="qwen3:8b")
    args=ap.parse_args()
    key=os.environ.get("GEMINI_API_KEY","").strip()
    if not key: raise SystemExit("Set GEMINI_API_KEY first.")

    root=Path(__file__).resolve().parents[1]
    folder=(root/"data"/"provider-failover-smoke").resolve()
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/"resume-proof.txt"
    target.unlink(missing_ok=True)
    expected="Conduit resumed on Ollama without repeating completed work"

    real_gemini=GeminiProvider(api_key=key)
    provider=FailAfterNProvider(real_gemini, fail_after_calls=1)

    goal=(
        f"Create the UTF-8 file {target} containing exactly {expected!r}. Then verify it exists and "
        "read it back to verify the exact content. Finish only after filesystem evidence proves success."
    )
    scope=ApprovalScope(
        goal=goal, allowed_actions=frozenset({"files.write_text"}),
        allowed_path_roots=(folder,), max_confirmed_actions=1,
        argument_constraints={"files.write_text":{"path":(str(target),),"text":(expected,)}},
    )
    print("\nFAILOVER TEST APPROVAL\n")
    print(scope.describe())
    if input("\nType YES to approve the one exact file write: ").strip()!="YES":
        raise SystemExit("Not approved.")
    approval=TaskApprovalSession(scope); approval.approve()

    events=EventBus()
    switched=False
    async def show(e):
        nonlocal switched
        if e.name=="agent.provider.switched": switched=True
        if e.name.startswith(("general_pc.","agent.provider","agent.decision","agent.observation","execution.confirmation")):
            print(f"EVENT {e.name}: {dict(e.payload)}")
    events.subscribe("*",show)

    async def recover(exc,current,current_model):
        print("\nSIMULATED GEMINI FAILURE DETECTED")
        print("Choosing the same option the UI will expose: Switch to Ollama.")
        ollama=OllamaProvider()
        models=await ollama.list_models()
        if args.ollama_model not in models:
            await ollama.close()
            raise RuntimeError(f"Ollama model {args.ollama_model!r} is not installed. Available: {models}")
        return ProviderReplacement(ollama,args.ollama_model,"Live smoke test selected Switch to Ollama.")

    agent=await GeneralPCAgent.create(
        provider=provider, model=args.gemini_model,
        config=GeneralPCAgentConfig(max_iterations=12),
        event_bus=events, approval_session=approval,
        provider_recovery_handler=recover,
    )
    try:
        report=await agent.run(goal,initial_variables={"target_path":str(target),"expected_text":expected})
    finally:
        await agent.close()

    writes=[o for o in report.observations if o.action=="files.write_text" and o.success]
    verified=target.exists() and target.read_text(encoding="utf-8")==expected
    print("\nFAILOVER REPORT")
    print("PROVIDER SWITCH OBSERVED:",switched)
    print("SUCCESSFUL FILE WRITES:",len(writes))
    print("FINAL PROVIDER:",agent.model)
    print("STATUS:",report.status.value)
    print("SUCCESS:",report.success)
    if not switched or len(writes)!=1 or not verified or not report.success:
        raise SystemExit("Provider failover did not preserve/resume the task correctly.")
    print("PROVIDER FAILOVER LIVE TEST: PASS")

if __name__=="__main__":
    asyncio.run(main())
