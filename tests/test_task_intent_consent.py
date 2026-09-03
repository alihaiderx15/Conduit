
import asyncio

from conduit.agent.executor import PlanExecutor
from conduit.planning import PlanStep, StepCapability


class Dummy:
    async def emit(self, *args, **kwargs):
        return None


def _executor():
    return PlanExecutor(
        browser=object(),
        tools=object(),
        event_bus=Dummy(),
        default_retries=0,
        task_intent_consent=True,
    )


def test_non_destructive_confirmed_action_is_authorized_by_task_intent():
    step = PlanStep(
        id="1",
        title="Paste text",
        capability=StepCapability.DESKTOP,
        action="desktop.hotkey",
        arguments={"keys": ["ctrl", "v"]},
        requires_confirmation=True,
    )
    assert asyncio.run(_executor()._confirm(step)) is True


def test_delete_still_requires_separate_confirmation():
    step = PlanStep(
        id="1",
        title="Delete file",
        capability=StepCapability.TOOL,
        action="files.delete",
        arguments={"path": "test.txt"},
        requires_confirmation=True,
    )
    assert asyncio.run(_executor()._confirm(step)) is False
