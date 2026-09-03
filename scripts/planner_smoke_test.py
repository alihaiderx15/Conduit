from __future__ import annotations
import argparse, asyncio, os
from conduit.events import EventBus
from conduit.planning import TaskPlanner
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini","ollama"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--goal", default="Open YouTube and play the current livestream from the Joka channel")
    args=parser.parse_args()
    provider = GeminiProvider(os.environ.get("GEMINI_API_KEY", "")) if args.provider=="gemini" else OllamaProvider()
    events=EventBus()
    async def show(event): print(f"EVENT {event.name}: {dict(event.payload)}")
    events.subscribe("plan.*", show)
    planner=TaskPlanner(provider=provider, model=args.model, event_bus=events)
    try:
        plan=await planner.create_plan(args.goal)
        print(f"\nGOAL: {plan.goal}\nSUMMARY: {plan.summary}\n")
        for step in plan.steps:
            marker=" [CONFIRM]" if step.requires_confirmation else ""
            print(f"{step.id}. {step.title}{marker}")
            print(f"   {step.capability.value} -> {step.action}")
            print(f"   arguments: {dict(step.arguments)}")
            print(f"   depends_on: {list(step.depends_on)}")
            print(f"   success: {step.success_criteria}\n")
        print("Plan generation only. No action was executed.")
    finally:
        await provider.close()

if __name__ == "__main__": asyncio.run(main())
