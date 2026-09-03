
from conduit.dynamic_agent.completion import RecentFileNotepadVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


def obs(i, action, data, arguments=None):
    return AgentObservation(
        iteration=i,
        action=action,
        arguments=arguments or {},
        success=True,
        message="ok",
        data=data,
    )


def test_recent_file_notepad_verifier_requires_all_evidence():
    expected = "newest content"
    path = r"C:\source\newest.txt"
    ctx = AgentContext(
        "Find the most recent file, use the clipboard, open Notepad, and verify everything.",
        {
            "source_dir": r"C:\source",
            "expected_source_path": path,
            "expected_text": expected,
            "target_window_bounds": {"x": 120, "y": 100, "width": 900, "height": 600},
        },
    )
    ctx.add_observation(obs(1, "files.list_recent", {"files": [{"path": path}]}))
    ctx.add_observation(obs(2, "files.read_text", {"path": path, "content": expected}))
    ctx.add_observation(obs(3, "clipboard.write", {"characters": len(expected)}))
    ctx.add_observation(obs(4, "system.open_app", {"app": "notepad", "command": "notepad.exe"}))
    ctx.add_observation(obs(5, "system.activate_window", {"title": "Untitled - Notepad"}))
    ctx.add_observation(obs(6, "desktop.hotkey", {"keys": ("ctrl", "v")}))
    ctx.add_observation(obs(7, "system.move_resize_window", {"title": "Untitled - Notepad"}))
    ctx.add_observation(obs(8, "clipboard.read", {"text": expected}))
    ctx.add_observation(obs(9, "system.window_bounds", {
        "title": "Untitled - Notepad", "x": 120, "y": 100, "width": 900, "height": 600,
    }))

    incomplete = RecentFileNotepadVerifier().verify(ctx)
    assert incomplete.applicable
    assert not incomplete.complete

    ctx.add_observation(obs(10, "system.process_info", {
        "process": "notepad.exe", "running": True,
    }))
    assert RecentFileNotepadVerifier().verify(ctx).complete
