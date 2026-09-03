
from conduit.dynamic_agent.parser import parse_decision


def test_web_aliases_map_to_registered_actions():
    decision = parse_decision(
        '{"decision":"act","reason":"search live web","action":"web_search",'
        '"arguments":{"query":"current Python news"}}',
        allowed_actions={"web.search"},
    )
    assert decision.action == "web.search"

    decision = parse_decision(
        '{"decision":"act","reason":"compare products","action":"compare_items",'
        '"arguments":{"items":["A","B"]}}',
        allowed_actions={"web.compare"},
    )
    assert decision.action == "web.compare"
