
import pytest
from types import SimpleNamespace

from conduit.conversation.session import ConversationSession
from conduit.conversation.search_planner import AISearchPlanner


class Provider:
    def __init__(self):
        self.prompts = []

    async def chat(self, messages, model=None):
        prompt = messages[-1].content
        self.prompts.append(prompt)
        return SimpleNamespace(text='{"action":"web.search","arguments":{"query":"Formula 1 all-time driver wins records","limit":8,"use_grounding":true,"region":"wt-wt"},"intent":"verify ranking","subject":"Formula 1 career wins","rewritten_request":"top Formula 1 drivers by career wins","answer_style":"concise","sources_requested":true,"query_variants":["Formula 1 all-time driver wins records","Lewis Hamilton career wins Formula 1","Michael Schumacher career wins Formula 1"],"exclude_terms":[],"source_preferences":["official","statistics"],"notes":[]}')


@pytest.mark.asyncio
async def test_search_planner_receives_untrusted_hypothesis():
    provider = Provider()
    planner = AISearchPlanner(provider, "fake")
    plan = await planner.plan(
        "top three F1 drivers by career wins and give sources",
        allowed_actions={"web.search"},
        evidence_hypothesis="Likely leaders include Hamilton and Schumacher; verify totals.",
    )
    assert plan.action == "web.search"
    assert len(plan.query_variants) >= 2
    prompt = provider.prompts[0]
    assert "MODEL HYPOTHESIS TO VERIFY" in prompt
    assert "not trusted evidence" in prompt
    assert "Hamilton" in prompt


def test_source_requests_are_evidence_augmented():
    assert ConversationSession._sources_or_verification_requested(
        "show the top three cricket batters and give me sources"
    )
    assert ConversationSession._sources_or_verification_requested("verify this ranking")
    assert not ConversationSession._sources_or_verification_requested("compare two GPUs")
