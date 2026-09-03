
from conduit.dynamic_agent.parser import parse_decision


def test_list_process_filter_maps_to_process_info():
    decision=parse_decision(
        '{"decision":"act","reason":"check","action":"system.list_processes",'
        '"arguments":{"name":"notepad"}}',
        allowed_actions={"system.list_processes","system.process_info"},
    )
    assert decision.action=="system.process_info"
    assert decision.arguments=={"process":"notepad"}


def test_activate_window_process_name_maps_to_title():
    decision=parse_decision(
        '{"decision":"act","reason":"focus","action":"system.activate_window",'
        '"arguments":{"process_name":"notepad.exe"}}',
        allowed_actions={"system.activate_window"},
    )
    assert decision.arguments=={"title":"notepad"}
