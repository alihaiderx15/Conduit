"""Provider-neutral task planner."""
from __future__ import annotations
import json
from conduit.core.models import ChatMessage, Role
from conduit.events import EventBus, EventNames
from conduit.providers.base import AIProvider
from .catalog import default_capabilities
from .errors import PlanningError
from .models import PlanningCapability, TaskPlan
from .parser import parse_plan


class TaskPlanner:
    def __init__(self, *, provider: AIProvider, model: str,
                 capabilities: tuple[PlanningCapability, ...] | None = None,
                 event_bus: EventBus | None = None, max_steps: int = 20,
                 max_attempts: int = 2) -> None:
        self.provider = provider
        self.model = model
        self.capabilities = capabilities or default_capabilities()
        self.events = event_bus
        self.max_steps = max_steps
        self.max_attempts = max_attempts

    async def create_plan(self, goal: str) -> TaskPlan:
        goal = goal.strip()
        if not goal:
            raise ValueError("A planning goal is required.")
        await self._emit(EventNames.PLAN_STARTED, {"goal": goal})
        prompt = self._prompt(goal)
        last_error: Exception | None = None
        messages = [ChatMessage(Role.SYSTEM, self._system_prompt()), ChatMessage(Role.USER, prompt)]
        for attempt in range(1, self.max_attempts + 1):
            response = await self.provider.chat(messages, model=self.model)
            try:
                plan = parse_plan(
                    response.text,
                    allowed_actions=(item.name for item in self.capabilities),
                    max_steps=self.max_steps,
                )
                await self._emit(EventNames.PLAN_COMPLETED, {
                    "goal": goal, "steps": len(plan.steps), "attempt": attempt,
                    "requires_confirmation": plan.requires_confirmation,
                })
                return plan
            except PlanningError as exc:
                last_error = exc
                messages.extend([
                    ChatMessage(Role.ASSISTANT, response.text),
                    ChatMessage(Role.USER, f"Your plan was invalid: {exc}. Return corrected JSON only."),
                ])
        await self._emit(EventNames.PLAN_FAILED, {"goal": goal, "error": str(last_error)})
        raise PlanningError(f"Unable to create a valid plan: {last_error}")

    def _system_prompt(self) -> str:
        return (
            "You are Conduit's task planner. Convert one user goal into a minimal, safe, "
            "ordered plan using only the supplied actions. Do not execute anything. "
            "Prefer browser actions for websites and desktop/vision actions for native apps. "
            "Prefer a supplied high-level capability when it directly completes the goal; "
            "otherwise combine low-level actions. Use ask_user only when essential information "
            "is missing. Return JSON only."
        )

    def _prompt(self, goal: str) -> str:
        caps = [{
            "action": item.name,
            "capability": item.capability.value,
            "description": item.description,
            "arguments": dict(item.arguments),
            "requires_confirmation": item.requires_confirmation,
        } for item in self.capabilities]
        schema = {
            "goal": "string", "summary": "string", "assumptions": ["string"],
            "steps": [{
                "id": "step_1", "title": "string",
                "capability": "tool|browser|desktop|vision|user",
                "action": "one supplied action", "arguments": {},
                "depends_on": [], "requires_confirmation": False,
                "success_criteria": "observable outcome",
            }],
        }
        return (
            f"USER GOAL:\n{goal}\n\nAVAILABLE ACTIONS:\n"
            f"{json.dumps(caps, indent=2)}\n\nREQUIRED JSON SHAPE:\n"
            f"{json.dumps(schema, indent=2)}\n\n"
            "Rules: each dependency must reference an earlier step; copy confirmation requirements "
            "from the action catalog; use the fewest reliable steps; never invent an action."
        )

    async def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self.events is not None:
            await self.events.emit(name, source="TaskPlanner", payload=payload)
