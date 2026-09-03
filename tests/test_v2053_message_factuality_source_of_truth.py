import asyncio
from types import SimpleNamespace

from conduit.conversation.session import ConversationSession
from conduit.core.models import ProviderResponse
from conduit.messaging.models import MessagingPlan


class HallucinatingProvider:
    def __init__(self):
        self.prompts = []

    async def specialist_chat(self, messages, *, model=None, **kwargs):
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            # Simulate the exact kind of unsupported addition seen in the real test.
            return ProviderResponse(
                text=(
                    "Understood. Let's reschedule the meeting for another day when "
                    "you're feeling better. If there's anything else I can assist with, "
                    "please let me know!"
                )
            )
        return ProviderResponse(
            text="I wanted to let you know that I won't be able to come tomorrow because I have a fever. Thank you for understanding."
        )

    async def chat(self, messages, *, model=None, **kwargs):
        return await self.specialist_chat(messages, model=model, **kwargs)


def _session(provider):
    session = ConversationSession.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=provider, model="test-model"))
    return session


def test_audit_uses_original_user_request_not_router_hallucination():
    provider = HallucinatingProvider()
    session = _session(provider)
    original = "open discord chat with uzair and tell him iam not coming tomorrow due to fever make it professional"
    plan = MessagingPlan(
        action="messaging.send",
        service="discord",
        recipient="uzair",
        message="",
        # Deliberately poisoned router hint. This must NOT become factual truth.
        compose_instruction="Professionally tell Uzair to reschedule tomorrow's meeting because the user is sick.",
    )

    result = asyncio.run(session._compose_messaging_text(original, plan))

    assert "meeting" not in result.casefold()
    assert "resched" not in result.casefold()
    assert "tomorrow" in result.casefold()
    assert "fever" in result.casefold()
    assert len(provider.prompts) == 2
    assert f"ORIGINAL USER REQUEST:\n{original}" in provider.prompts[0]
    assert f"ORIGINAL USER REQUEST:\n{original}" in provider.prompts[1]
    assert "ROUTER COMPOSITION HINT (NON-AUTHORITATIVE)" in provider.prompts[0]
    assert "sole source of factual truth" in provider.prompts[1]


def test_composer_does_not_use_router_hint_as_original_instruction():
    from pathlib import Path
    from conduit.conversation import session as session_module

    source = Path(session_module.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _compose_messaging_text"):
        source.index("async def _prepare_messaging_client")
    ]
    assert "original_request = user_message.strip()" in block
    assert "composition_hint = (plan.compose_instruction or \"\").strip()" in block
    assert "ORIGINAL USER REQUEST" in block
    assert "NON-AUTHORITATIVE" in block
