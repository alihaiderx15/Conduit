from types import MethodType

import pytest

from conduit.conversation.session import ConversationSession
from conduit.core.models import ChatMessage, ProviderResponse, Role
from conduit.core.prompting import load_core_prompt, with_core_prompt
from conduit.providers.ollama import OllamaProvider


def test_core_prompt_identity_and_voice_style():
    prompt = load_core_prompt()
    assert "CONDUIT CORE PROTOCOL" in prompt
    assert "Conduit" in prompt
    assert "Ali Haider" in prompt
    assert "desktop AI copilot" in prompt
    assert "one to three natural paragraphs" in prompt
    assert "Do NOT use headings" in prompt
    assert "Windows default browser" in prompt


def test_core_prompt_is_prepended_only_once():
    messages = (ChatMessage(Role.USER, "hello"),)
    once = with_core_prompt(messages)
    twice = with_core_prompt(once)
    assert once == twice
    assert once[0].role is Role.SYSTEM
    assert "CONDUIT CORE PROTOCOL" in once[0].content


@pytest.mark.asyncio
async def test_ollama_provider_injects_core_prompt_into_chat_payload():
    provider = OllamaProvider()
    captured = {}

    async def fake_post(self, payload):
        captured.update(payload)
        return {"model": "fake", "message": {"content": "ok"}}

    provider._post_chat = MethodType(fake_post, provider)
    try:
        response = await provider.chat(
            [ChatMessage(Role.USER, "Who are you?")],
            model="fake",
        )
        assert response.text == "ok"
        assert captured["messages"][0]["role"] == "system"
        assert "CONDUIT CORE PROTOCOL" in captured["messages"][0]["content"]
    finally:
        await provider.close()


def test_default_conversation_style_is_voice_friendly_paragraphs():
    session = object.__new__(ConversationSession)
    text = session._conversation_style_instruction("compare these", search_plan=None)
    assert "one to three short paragraphs" in text
    assert "numbered lists" in text
    assert "bullet lists" in text
    assert "unless the user explicitly asks" in text
