from pathlib import Path

from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.planning import PlanStep, StepCapability


def _step(action, arguments=None):
    return PlanStep(
        id="s1", title="test", capability=StepCapability.DESKTOP,
        action=action, arguments=arguments or {}, requires_confirmation=True,
    )


def test_scope_authorizes_only_approved_actions_and_arguments(tmp_path):
    scope = ApprovalScope(
        goal="Save a note",
        allowed_actions=frozenset({"desktop.type", "files.write_text"}),
        allowed_path_roots=(tmp_path,),
        argument_constraints={"desktop.type": {"text": ("hello",)}},
    )
    session = TaskApprovalSession(scope)
    session.approve()
    assert session.authorize(_step("desktop.type", {"text": "hello"}))[0]
    assert not session.authorize(_step("desktop.type", {"text": "bad"}))[0]
    assert not session.authorize(_step("desktop.click", {"target": "Delete"}))[0]
    assert session.authorize(_step("files.write_text", {"path": str(tmp_path / "a.txt"), "text": "x"}))[0]
    assert not session.authorize(_step("files.write_text", {"path": str(tmp_path.parent / "outside.txt"), "text": "x"}))[0]


def test_scope_requires_explicit_approval():
    session = TaskApprovalSession(ApprovalScope("goal", frozenset({"desktop.type"})))
    approved, _ = session.authorize(_step("desktop.type", {"text": "hello"}))
    assert not approved
