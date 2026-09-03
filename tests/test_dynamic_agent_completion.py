
import asyncio
from pathlib import Path

import pytest

from conduit.dynamic_agent.completion import StructuredFileGoalVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


def obs(i, action, path, data=None):
    return AgentObservation(
        iteration=i,
        action=action,
        arguments={"path": path},
        success=True,
        message="ok",
        data=data or {"path": path},
    )


def test_structured_file_goal_verifier_requires_concrete_evidence():
    path = r"C:\\tmp\\proof.txt"
    ctx = AgentContext(
        "Create the file, verify it exists, read exact contents, then open it.",
        {"target_path": path, "expected_text": "hello"},
    )
    verifier = StructuredFileGoalVerifier()

    ctx.add_observation(obs(1, "files.write_text", path))
    assert not verifier.verify(ctx).complete

    ctx.add_observation(obs(2, "files.read_text", path, {"path": path, "content": "hello"}))
    assert not verifier.verify(ctx).complete

    ctx.add_observation(obs(3, "system.open_path", path))
    assert not verifier.verify(ctx).complete

    ctx.add_observation(obs(4, "files.exists", path, {"path": path, "exists": True}))
    result = verifier.verify(ctx)
    assert result.complete
    assert "filesystem evidence" in result.message


def test_structured_file_goal_verifier_rejects_wrong_content():
    path = r"C:\\tmp\\proof.txt"
    ctx = AgentContext(
        "Create the file and verify it exists.",
        {"target_path": path, "expected_text": "hello"},
    )
    ctx.add_observation(obs(1, "files.write_text", path))
    ctx.add_observation(obs(2, "files.read_text", path, {"path": path, "content": "wrong"}))
    ctx.add_observation(obs(3, "files.exists", path, {"path": path, "exists": True}))
    assert not StructuredFileGoalVerifier().verify(ctx).complete
