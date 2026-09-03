import pytest
from conduit.agent import PlanExecutor, StepStatus
from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.planning import PlanStep, StepCapability


class FakeBrowser: pass
class FakeTools: pass
class FakeRouter:
    async def execute(self, step):
        from conduit.actions import ActionOutcome
        return ActionOutcome(True, "done")


@pytest.mark.asyncio
async def test_executor_uses_task_scope_without_per_step_handler():
    session = TaskApprovalSession(ApprovalScope("type", frozenset({"desktop.type"})))
    session.approve()
    executor = PlanExecutor(browser=FakeBrowser(), tools=FakeTools(), action_router=FakeRouter(), approval_session=session, default_retries=0)
    step = PlanStep("s1", "type", StepCapability.DESKTOP, "desktop.type", {"text": "hello"}, requires_confirmation=True)
    result = await executor.execute_step(step)
    assert result.status is StepStatus.COMPLETED


@pytest.mark.asyncio
async def test_executor_blocks_out_of_scope_action():
    session = TaskApprovalSession(ApprovalScope("type", frozenset({"desktop.type"})))
    session.approve()
    executor = PlanExecutor(browser=FakeBrowser(), tools=FakeTools(), action_router=FakeRouter(), approval_session=session, default_retries=0)
    step = PlanStep("s1", "click", StepCapability.DESKTOP, "desktop.click", {"target": "Delete"}, requires_confirmation=True)
    result = await executor.execute_step(step)
    assert result.status is StepStatus.CANCELLED
