from types import SimpleNamespace

import pytest

from conduit.conversation import ConversationSession
from conduit.core.models import ProviderResponse


class CapturingProvider:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages, *, model, tools=()):
        prompt = messages[-1].content
        self.prompts.append(prompt)
        if "CONVERSATION INTENT ROUTER" in prompt:
            return ProviderResponse(
                text='{"route":"direct","web_needed":false,"browser_requested":false,"normalized_request":"Compare A and B","intent":"comparison"}',
                model=model,
            )
        return ProviderResponse(text="A is the better fit overall because it has the advantages that matter most here.", model=model)


class Agent:
    def __init__(self):
        provider = CapturingProvider()
        self.loop = SimpleNamespace(provider=provider, model="fake")
        self.events = SimpleNamespace()
        self.calls = []

    async def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("direct answer should not execute the tool loop")


@pytest.mark.asyncio
async def test_default_direct_response_prompt_is_spoken_style():
    agent = Agent()
    session = ConversationSession(agent)
    answer, report = await session.ask("Compare A and B")
    assert report.status.value == "direct_answer"
    assert "better fit" in answer
    final_prompt = agent.loop.provider.prompts[-1]
    assert "one to three short paragraphs" in final_prompt
    assert "Avoid headings" in final_prompt


@pytest.mark.asyncio
async def test_detailed_request_allows_longer_response():
    agent = Agent()
    session = ConversationSession(agent)
    await session.ask("Give me a detailed comparison of A and B")
    final_prompt = agent.loop.provider.prompts[-1]
    assert "explicitly asked for detail" in final_prompt
