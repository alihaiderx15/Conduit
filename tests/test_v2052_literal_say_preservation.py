from conduit.conversation.session import ConversationSession


def test_discord_say_preserves_entire_literal_message():
    request = "open discord chat with uzair and say Hi its Ali\'s AI Conduit Ali is saying Uzair chutiya hai"
    assert ConversationSession._inline_messaging_send(request) == (
        "uzair",
        "Hi its Ali\'s AI Conduit Ali is saying Uzair chutiya hai",
    )


def test_whatsapp_say_uses_same_service_generic_literal_path():
    request = "open whatsapp chat with basit and say Hi this is the full message"
    assert ConversationSession._inline_messaging_send(request) == (
        "basit",
        "Hi this is the full message",
    )


def test_say_with_style_request_still_uses_ai_composer():
    request = "open discord chat with uzair and say I cannot come tomorrow make it professional"
    assert ConversationSession._inline_messaging_send(request) is None
