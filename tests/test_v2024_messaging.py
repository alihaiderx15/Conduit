
from types import SimpleNamespace

import pytest

from conduit.conversation.session import ConversationSession
from conduit.messaging import AIMessagingRouter
from conduit.tools.builtin import registry


def test_messaging_actions_registered_and_send_is_confirm():
    for name in (
        "messaging.resolve_contact",
        "messaging.open_chat",
        "messaging.read_recent",
        "messaging.send",
    ):
        assert registry.get(name).name == name
    assert registry.get("messaging.send").risk.value == "confirm"
    assert registry.get("messaging.open_chat").risk.value == "safe"
    assert registry.get("messaging.read_recent").risk.value == "safe"


def test_messaging_request_detection():
    class Agent:
        pass
    session = ConversationSession(Agent())
    assert session._could_be_messaging_request(
        "send Ahmed a message on WhatsApp"
    )
    assert session._could_be_messaging_request(
        "read my last message from Ali on Telegram"
    )
    assert not session._could_be_messaging_request(
        "what is WhatsApp"
    )


def test_fallback_send_plan_is_generic():
    plan = ConversationSession._fallback_messaging_plan(
        "send my boss a professional message on whatsapp saying I am sick"
    )
    assert plan.action == "messaging.send"
    assert plan.service == "whatsapp"
    assert "boss" in plan.compose_instruction


class Provider:
    async def chat(self, messages, model=None):
        return SimpleNamespace(text='{"action":"messaging.send","service":"whatsapp","recipient":"my boss","message":"","compose_instruction":"Tell my boss I am sick today in a professional tone"}')


@pytest.mark.asyncio
async def test_ai_router_distinguishes_composed_message():
    plan = await AIMessagingRouter(Provider(), model="fake").plan(
        "send my boss a professional whatsapp message and tell him I am sick"
    )
    assert plan.action == "messaging.send"
    assert plan.recipient == "my boss"
    assert plan.message == ""
    assert "professional" in plan.compose_instruction


def test_service_config_is_generic():
    from conduit.messaging.service import SERVICE_CONFIG
    assert "whatsapp" in SERVICE_CONFIG
    assert "telegram" in SERVICE_CONFIG
    assert SERVICE_CONFIG["whatsapp"]["web_url"].startswith("https://")
    assert SERVICE_CONFIG["telegram"]["web_url"].startswith("https://")


def test_shell_has_explicit_pending_send_gate():
    from pathlib import Path
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert 'pending_message' in source
    assert 'confirm_pending_message(True)' in source
    assert 'confirm_pending_message(False)' in source
