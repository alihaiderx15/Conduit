
from conduit.dynamic_agent.parser import parse_decision


ALLOWED = {
    "system.open_app",
    "system.activate_window",
    "system.move_resize_window",
}


def test_real_world_v12_aliases():
    launch = parse_decision(
        '{"decision":"act","reason":"launch","action":"system.launch_app",'
        '"arguments":{"application":"notepad"}}',
        allowed_actions=ALLOWED,
    )
    assert launch.action == "system.open_app"

    activate = parse_decision(
        '{"decision":"act","reason":"focus","action":"desktop.activate_window",'
        '"arguments":{"window_title":"Notepad"}}',
        allowed_actions=ALLOWED,
    )
    assert activate.action == "system.activate_window"
    assert activate.arguments["title"] == "Notepad"

    bounds = parse_decision(
        '{"decision":"act","reason":"resize","action":"desktop.set_window_bounds",'
        '"arguments":{"title":"Notepad","x":120,"y":100,"width":900,"height":600}}',
        allowed_actions=ALLOWED,
    )
    assert bounds.action == "system.move_resize_window"
