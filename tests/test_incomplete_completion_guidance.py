
from conduit.dynamic_agent.completion import RecentFileNotepadVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


def test_unseen_task_verifier_lists_remaining_evidence_after_read():
    expected = "newest"
    source = r"C:\source\newest.txt"
    ctx = AgentContext(
        "Find the most recent file, use the clipboard, open Notepad, and verify everything.",
        {
            "source_dir": r"C:\source",
            "expected_source_path": source,
            "expected_text": expected,
            "target_window_bounds": {"x": 120, "y": 100, "width": 900, "height": 600},
        },
    )
    ctx.add_observation(AgentObservation(
        iteration=1,
        action="files.list_recent",
        arguments={},
        success=True,
        message="ok",
        data={"files": [{"path": source}]},
    ))
    ctx.add_observation(AgentObservation(
        iteration=2,
        action="files.read_text",
        arguments={},
        success=True,
        message="ok",
        data={"path": source, "content": expected},
    ))
    evidence = RecentFileNotepadVerifier().verify(ctx)
    assert evidence.applicable
    assert not evidence.complete
    assert "clipboard write" in evidence.message
    assert "Notepad launch" in evidence.message
