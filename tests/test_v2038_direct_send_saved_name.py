
from types import SimpleNamespace
from pathlib import Path

from conduit.conversation.session import ConversationSession
from conduit.messaging.models import MessagingPlan


class DummyAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=None, model="fake")


def test_inline_open_and_message_becomes_send():
    session = ConversationSession(DummyAgent())
    parsed = session._inline_messaging_send(
        "open the chat of maryam in whatsapp and message Hi"
    )
    assert parsed == ("maryam", "Hi")


def test_inline_open_and_message_with_active_service():
    session = ConversationSession(DummyAgent())
    parsed = session._inline_messaging_send(
        "open the chat of basit and message Hi"
    )
    assert parsed == ("basit", "Hi")


def test_professional_instruction_is_not_forced_into_exact_message():
    session = ConversationSession(DummyAgent())
    assert session._inline_messaging_send(
        "open chat with boss on whatsapp and message him I am sick make it professional"
    ) is None


def test_chat_verification_requests_exact_saved_header():
    source = Path(__file__).resolve().parents[1] / "conduit" / "conversation" / "session.py"
    text = source.read_text(encoding="utf-8")
    block = text[
        text.index("async def _resolve_messaging_contact"):
        text.index("async def _execute_messaging_plan")
    ]
    assert "CHAT_NAME <exact visible saved contact/chat header>" in block
    assert "Preserve the visible saved header" in block
    assert 'line.upper().startswith("CHAT_NAME ")' in block


def test_send_path_does_not_locate_composer():
    source = Path(__file__).resolve().parents[1] / "conduit" / "conversation" / "session.py"
    text = source.read_text(encoding="utf-8")
    block = text[
        text.index("async def _execute_messaging_plan"):
        text.index("async def confirm_pending_message")
    ]
    assert "locate_message_composer_center" not in block
    assert "click_service_xy" not in block
    assert "type_service_text(self.agent, service, client, final_message)" not in block
    assert "do NOT type or paste anything" in block


def test_confirmation_uses_resolved_saved_contact_name():
    source = Path(__file__).resolve().parents[1] / "conduit" / "conversation" / "session.py"
    text = source.read_text(encoding="utf-8")
    block = text[
        text.index("async def _execute_messaging_plan"):
        text.index("async def confirm_pending_message")
    ]
    assert '"pending_recipient": resolved' in block
    assert "prepared this message for {resolved}" in block


def test_planner_prioritizes_send_for_combined_request():
    source = Path(__file__).resolve().parents[1] / "conduit" / "messaging" / "planner.py"
    text = source.read_text(encoding="utf-8")
    assert "the action is messaging.send, not messaging.open_chat" in text
