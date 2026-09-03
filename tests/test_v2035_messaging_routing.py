
from types import SimpleNamespace

from conduit.conversation.session import ConversationSession


class DummyAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=None, model="fake")


def test_open_whatsapp_chat_word_order_routes_to_messaging():
    session = ConversationSession(DummyAgent())
    assert session._could_be_messaging_request("open whatsapp chat with basit")
    assert session._could_be_messaging_request("open whatsapp chat with maryam")
    assert session._could_be_messaging_request("open chat with basit on whatsapp")


def test_open_whatsapp_with_contact_routes_without_literal_chat_word():
    session = ConversationSession(DummyAgent())
    assert session._could_be_messaging_request("open whatsapp with basit")


def test_plain_whatsapp_question_does_not_route():
    session = ConversationSession(DummyAgent())
    assert not session._could_be_messaging_request("what is whatsapp")


def test_fallback_extracts_recipient_from_interleaved_word_order():
    plan = ConversationSession._fallback_messaging_plan(
        "open whatsapp chat with basit"
    )
    assert plan is not None
    assert plan.action == "messaging.open_chat"
    assert plan.service == "whatsapp"
    assert plan.recipient.casefold() == "basit"


def test_dedicated_messaging_route_precedes_youtube_and_generic_agent():
    from pathlib import Path
    import conduit.conversation.session as session_mod
    source = Path(session_mod.__file__).read_text(encoding="utf-8")
    ask_start = source.index("async def ask")
    messaging_index = source.index("_could_be_messaging_request", ask_start)
    youtube_index = source.index("_could_be_youtube_request", ask_start)
    generic_index = source.index("self.agent.run", ask_start)
    assert messaging_index < youtube_index < generic_index
