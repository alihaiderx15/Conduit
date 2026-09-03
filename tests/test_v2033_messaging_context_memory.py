
from types import SimpleNamespace
from pathlib import Path

from conduit.conversation.session import ConversationSession, ConversationTurn
from conduit.observer.models import ScreenCapture
from conduit.observer.parser import parse_structured_screen_analysis


class DummyAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=None, model="fake")


def test_history_text_exists_and_renders_recent_turns():
    session = ConversationSession(DummyAgent())
    session.history = [
        ConversationTurn("open Maryam on whatsapp", "I opened Maryam Sister."),
        ConversationTurn("hello", "Hi."),
    ]
    text = session._history_text()
    assert "open Maryam on whatsapp" in text
    assert "I opened Maryam Sister." in text


def test_messaging_followup_detected_without_repeating_whatsapp():
    session = ConversationSession(DummyAgent())
    session._messaging_context = {
        "service": "whatsapp",
        "last_action": "messaging.open_chat",
        "attempted_recipient": "khokar goli",
    }
    assert session._could_be_messaging_request("try khokhar goli")


def test_clear_resets_messaging_context_too():
    session = ConversationSession(DummyAgent())
    session._messaging_context = {"service":"whatsapp","recipient":"Maryam"}
    session.history = [ConversationTurn("x","y")]
    session.clear()
    assert session.history == []
    assert session._messaging_context == {}


def test_parser_repairs_unquoted_keys_and_trailing_comma():
    capture = ScreenCapture(
        image_path=Path("screen.png"),
        width=1920,
        height=1080,
        captured_at="test",
    )
    raw = '''
    {
      "application": "WhatsApp",
      "summary": "Maryam search results",
      "elements": [
        {
          "id": "maryam",
          "label": "Maryam Sister",
          "role": "listitem",
          "bounds": {"x": 20, "y": 100, width: 400, height: 60,},
          "confidence": 0.96,
          "text": "Maryam Sister",
          "enabled": True,
          "visible": True,
        },
      ],
    }
    '''
    result = parse_structured_screen_analysis(
        raw,
        capture=capture,
        provider_id="ollama",
        model="qwen2.5vl:7b",
    )
    assert result.application == "WhatsApp"
    assert result.elements[0].label == "Maryam Sister"
