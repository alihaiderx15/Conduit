from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.messaging.models import MessagingPlan


class Provider:
    def __init__(self):
        self.calls = 0

    async def specialist_chat(self, messages, *, model=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(text="I wanted to let you know that I won't be able to come tomorrow because I have a fever. Thank you for understanding.")
        if self.calls == 2:
            return SimpleNamespace(text="I'm sorry, but I cannot proceed with the audit as there is no draft message provided for review against the original user instruction. Please provide the draft message.")
        return SimpleNamespace(text="I wanted to let you know that I won't be able to come tomorrow because I have a fever. Thank you for understanding.")

    async def chat(self, messages, *, model=None, **kwargs):
        return await self.specialist_chat(messages, model=model, **kwargs)


@pytest.mark.asyncio
async def test_audit_meta_response_is_never_offered_as_message():
    provider = Provider()
    agent = SimpleNamespace(loop=SimpleNamespace(provider=provider, model="test"))
    session = ConversationSession(agent)
    original = "open discord chat with uzair and tell him iam not coming tomorrow due to fever make it professional"
    plan = MessagingPlan(
        action="messaging.send",
        service="discord",
        recipient="uzair",
        compose_instruction="Make it professional.",
    )
    result = await session._compose_messaging_text(original, plan)
    lowered = result.casefold()
    assert "cannot proceed with the audit" not in lowered
    assert "provide the draft" not in lowered
    assert "tomorrow" in lowered
    assert "fever" in lowered
    assert provider.calls == 3


def test_discord_readiness_poll_is_one_second():
    source = (Path(__file__).resolve().parents[1] / "conduit" / "conversation" / "session.py").read_text(encoding="utf-8")
    block = source[source.index("async def _prepare_messaging_client"):source.index("async def _resolve_messaging_contact")]
    assert "poll_seconds=1.0" in block
