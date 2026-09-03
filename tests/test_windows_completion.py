
from conduit.dynamic_agent.completion import WindowsClipboardProcessVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


def _obs(i, action, data):
    return AgentObservation(i, action, {}, True, "ok", data)


def test_windows_multiaction_completion():
    expected="Conduit General PC Agent v1.1"
    ctx=AgentContext(
        "Open Notepad, copy to clipboard, minimize Notepad, and verify it is running.",
        {"expected_text":expected},
    )
    ctx.add_observation(_obs(1,"desktop.type",{"length":len(expected)}))
    ctx.add_observation(_obs(2,"clipboard.read",{"text":expected}))
    ctx.add_observation(_obs(3,"system.window_state",{"state":"minimize"}))
    ctx.add_observation(_obs(4,"system.list_processes",{"processes":["notepad.exe"]}))
    assert WindowsClipboardProcessVerifier().verify(ctx).complete
