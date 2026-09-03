
from conduit.dynamic_agent.parser import parse_decision


ALLOWED = {
    "system.open_app",
    "system.activate_window",
    "clipboard.write",
}


def test_desktop_launch_app_aliases_to_system_open_app():
    decision = parse_decision(
        '{"decision":"act","reason":"open notepad","action":"desktop.launch_app",'
        '"arguments":{"application":"notepad"}}',
        allowed_actions=ALLOWED,
    )
    assert decision.action == "system.open_app"
    assert decision.arguments == {"app": "notepad"}


def test_safe_shell_notepad_aliases_to_system_open_app():
    decision = parse_decision(
        '{"decision":"act","reason":"open notepad","action":"shell.execute",'
        '"arguments":{"command":"notepad.exe"}}',
        allowed_actions=ALLOWED,
    )
    assert decision.action == "system.open_app"
    assert decision.arguments == {"app": "notepad"}


def test_arbitrary_shell_command_is_not_aliased():
    try:
        parse_decision(
            '{"decision":"act","reason":"run command","action":"shell.execute",'
            '"arguments":{"command":"powershell.exe something"}}',
            allowed_actions=ALLOWED,
        )
    except ValueError as exc:
        assert "Unsupported action" in str(exc)
    else:
        raise AssertionError("Arbitrary shell execution must remain unsupported.")
