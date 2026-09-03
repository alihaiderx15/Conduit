import asyncio
from types import SimpleNamespace

from conduit.conversation.session import ConversationSession
from conduit.core.models import ProviderResponse
from conduit.messaging.models import MessagingPlan


class ToneProvider:
    def __init__(self):
        self.prompts = []

    async def specialist_chat(self, messages, *, model=None, **kwargs):
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            # Simulate a safe but too-blunt first draft.
            return ProviderResponse(text="Uzair, I am not coming tomorrow due to fever.")
        return ProviderResponse(
            text=(
                "I wanted to let you know that I won't be able to come tomorrow because "
                "I have a fever. Thank you for understanding."
            )
        )

    async def chat(self, messages, *, model=None, **kwargs):
        return await self.specialist_chat(messages, model=model, **kwargs)


def _session(provider):
    session = ConversationSession.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=provider, model="test-model"))
    return session


def test_professional_audit_improves_blunt_safe_draft_without_new_facts():
    provider = ToneProvider()
    session = _session(provider)
    original = "open discord chat with uzair and tell him iam not coming tomorrow due to fever make it professional"
    plan = MessagingPlan(
        action="messaging.send",
        service="discord",
        recipient="uzair",
        message="",
        compose_instruction="Make the message professional.",
    )

    result = asyncio.run(session._compose_messaging_text(original, plan))
    low = result.casefold()
    assert "tomorrow" in low
    assert "fever" in low
    assert "meeting" not in low
    assert "resched" not in low
    assert "wanted to let you know" in low
    assert "thank you for understanding" in low
    assert "blunt, robotic" in provider.prompts[1]
    assert "safe non-factual courtesy/framing" in provider.prompts[1].casefold()


def test_professional_writer_prompt_allows_safe_courtesy_without_inventing_facts():
    from pathlib import Path
    from conduit.conversation import session as session_module

    source = Path(session_module.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _compose_messaging_text"):
        source.index("async def _prepare_messaging_client")
    ]
    assert "genuinely polished" in block
    assert "Thank you for understanding" in block
    assert "do not invent an external fact" in block
