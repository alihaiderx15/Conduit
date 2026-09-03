import pytest

from conduit.dynamic_agent import AgentDecisionError, AgentDecisionKind, parse_decision


def test_parses_act_decision():
    decision = parse_decision(
        '{"decision":"act","reason":"Open it","action":"browser.start","arguments":{},"expected_outcome":"browser ready"}',
        allowed_actions=["browser.start"],
    )
    assert decision.kind is AgentDecisionKind.ACT
    assert decision.action == "browser.start"


def test_extracts_json_from_code_fence():
    decision = parse_decision(
        '```json\n{"decision":"finish","reason":"Verified","message":"Done"}\n```',
        allowed_actions=[],
    )
    assert decision.kind is AgentDecisionKind.FINISH
    assert decision.message == "Done"


def test_rejects_unknown_action():
    with pytest.raises(AgentDecisionError):
        parse_decision(
            '{"decision":"act","reason":"Try","action":"invented","arguments":{}}',
            allowed_actions=["browser.start"],
        )


def test_parses_named_result_captures():
    decision = parse_decision(
        '{"decision":"act","reason":"Read page","action":"browser.read_page","arguments":{},'
        '"save_as":{"page_url":"data.url","page_title":"data.title"}}',
        allowed_actions=["browser.read_page"],
    )
    assert decision.save_as == {"page_url": "data.url", "page_title": "data.title"}


def test_parses_memory_proposals():
    decision = parse_decision(
        '{"decision":"finish","reason":"Stable preference learned","message":"Done",'
        '"memory_proposals":[{"key":"preferred_browser","value":"Opera",'
        '"category":"preference","importance":0.8,"reason":"User stated a durable preference"}]}',
        allowed_actions=[],
    )
    assert len(decision.memory_proposals) == 1
    proposal = decision.memory_proposals[0]
    assert proposal.key == "preferred_browser"
    assert proposal.category.value == "preference"
    assert proposal.importance == 0.8
