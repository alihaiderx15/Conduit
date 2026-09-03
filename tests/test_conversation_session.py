
from types import SimpleNamespace

import pytest

from conduit.conversation import ConversationSession
from conduit.core.models import ProviderResponse
from conduit.dynamic_agent.models import (
    AgentObservation,
    AgentRunReport,
    AgentRunStatus,
)


class FakeProvider:
    async def chat(self, messages, *, model, tools=()):
        content = messages[-1].content
        assert (
            "STRUCTURED EXECUTION EVIDENCE" in content
            or "WEB EXECUTION EVIDENCE" in content
        )
        return ProviderResponse(
            text=(
                "The observed Pakistani listing price is Rs. 125,000. "
                "Source: Example Store — https://example.com/rtx3070ti"
            ),
            model=model,
        )


class FakeAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=FakeProvider(), model="fake")
        self.goals = []

    async def run(self, goal, *, initial_variables=None, allowed_actions=None):
        self.goals.append((goal, initial_variables))
        return AgentRunReport(
            goal=goal,
            status=AgentRunStatus.COMPLETED,
            success=True,
            final_message="Price search completed.",
            observations=(
                AgentObservation(
                    iteration=1,
                    action="web.price_search",
                    arguments={"item": "RTX 3070 Ti", "region": "Pakistan"},
                    success=True,
                    message="Found a price.",
                    data={
                        "results": [
                            {
                                "title": "Example Store",
                                "url": "https://example.com/rtx3070ti",
                                "price": "Rs. 125,000",
                            }
                        ]
                    },
                ),
            ),
            variables={},
            iterations=2,
        )


@pytest.mark.asyncio
async def test_conversation_turn_returns_natural_answer():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask(
        "Find the price of RTX 3070 Ti in Pakistan"
    )
    assert report.success
    assert "Rs. 125,000" in answer
    assert "https://example.com/rtx3070ti" in answer
    assert len(session.history) == 1


@pytest.mark.asyncio
async def test_followup_includes_recent_conversation():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("Find the price of RTX 3070 Ti in Pakistan")
    # Ask for sources so this follow-up intentionally takes the hybrid/tool path.
    await session.ask("Compare that with RTX 4070 and give sources")
    second_goal, second_variables = agent.goals[1]
    assert "Compare that with RTX 4070" in second_goal
    assert second_variables["conversation_history_used"] is True
    assert any(
        "RTX 3070 Ti" in item["user"]
        for item in second_variables["conversation_history"]
    )


def test_clear_removes_conversation_history():
    session = ConversationSession(FakeAgent())
    session.history.append(
        __import__("conduit.conversation", fromlist=["ConversationTurn"])
        .ConversationTurn("hello", "hi")
    )
    session.clear()
    assert session.history == []
