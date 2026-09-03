
from pathlib import Path
from conduit.conversation.session import ConversationSession

def test_literal_message_stays_literal():
    assert ConversationSession._inline_messaging_send(
        "open the chat of maryam in whatsapp and message Hi"
    ) == ("maryam", "Hi")

def test_professional_message_goes_to_ai():
    assert ConversationSession._inline_messaging_send(
        "open the chat of maryam in whatsapp and message that i cannot come tomorrow make it professional"
    ) is None

def test_funny_message_goes_to_ai():
    assert ConversationSession._inline_messaging_send(
        "open chat with ali on whatsapp and message I cannot come tomorrow make it funny"
    ) is None

def test_application_and_letter_go_to_ai():
    assert ConversationSession._inline_messaging_send(
        "open chat with teacher on whatsapp and message I am ill as an application"
    ) is None
    assert ConversationSession._inline_messaging_send(
        "open chat with teacher on whatsapp and message I am ill make it letter style"
    ) is None

def test_composer_prompt_explicitly_supports_styles():
    source=(Path(__file__).resolve().parents[1]/"conduit"/"conversation"/"session.py").read_text(encoding="utf-8")
    block=source[source.index("async def _compose_messaging_text"):source.index("async def _prepare_messaging_client")]
    assert "message-writing brain" in block
    assert "professional/formal" in block
    assert "funny/humorous" in block
    assert "application/request" in block
    assert "email/mail" in block
    assert "letter" in block
