from types import SimpleNamespace

from conduit.conversation import ConversationSession
from conduit.dynamic_agent.completion import ConversationalWebActionVerifier
from conduit.dynamic_agent.context import AgentContext
from conduit.dynamic_agent.models import AgentObservation


class DummyAgent:
    loop = SimpleNamespace(provider=None, model='dummy')


def test_price_request_is_restricted_to_structured_price_search():
    session = ConversationSession(DummyAgent())
    assert session._conversation_web_actions(
        'Find the current price of an RTX 3070 Ti in Pakistan'
    ) == {'web.price_search'}


def test_no_browser_phrase_keeps_web_only_policy():
    session = ConversationSession(DummyAgent())
    assert session._conversation_web_actions(
        "Find the price, but don't open any browser on my screen"
    ) == {'web.price_search'}


def test_explicit_browser_control_disables_web_only_policy():
    session = ConversationSession(DummyAgent())
    assert session._conversation_web_actions(
        'Open the browser and navigate to example.com'
    ) == set()


def test_successful_structured_web_action_completes_turn():
    context = AgentContext(
        'Find a price',
        {'conversation_web_actions': ['web.price_search']},
    )
    verifier = ConversationalWebActionVerifier()
    assert verifier.verify(context).applicable
    assert not verifier.verify(context).complete

    context.add_observation(
        AgentObservation(
            iteration=1,
            action='web.price_search',
            arguments={'item': 'RTX 3070 Ti'},
            success=True,
            message='Search completed.',
            data={'results': []},
        )
    )
    assert verifier.verify(context).complete
