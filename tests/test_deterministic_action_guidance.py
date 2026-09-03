
from conduit.dynamic_agent.completion import RecentFileNotepadVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


def test_recent_file_verifier_recommends_clipboard_write_after_read():
    expected="hello"
    source=r"C:\source\newest.txt"
    ctx=AgentContext(
        "Find the most recent file, use the clipboard, open Notepad, and verify everything.",
        {
            "source_dir":r"C:\source",
            "expected_source_path":source,
            "expected_text":expected,
            "target_window_bounds":{"x":120,"y":100,"width":900,"height":600},
        },
    )
    ctx.add_observation(AgentObservation(
        1,"files.list_recent",{},True,"ok",{"files":[{"path":source}]}
    ))
    ctx.add_observation(AgentObservation(
        2,"files.read_text",{},True,"ok",{"path":source,"content":expected}
    ))
    evidence=RecentFileNotepadVerifier().verify(ctx)
    assert evidence.recommended_action=="clipboard.write"
    assert evidence.recommended_arguments=={"text":expected}
