
from types import SimpleNamespace

import pytest

from conduit.conversation import ConversationSession
from conduit.core.models import ProviderResponse
from conduit.dynamic_agent.models import (
    AgentObservation,
    AgentRunReport,
    AgentRunStatus,
)


class HallucinatingProvider:
    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(
            text=(
                "The RX 6700 XT has 16GB and supports DLSS 1.0. "
                "The RTX card uses 250W. [S1]\n\n"
                "Sources:\n[S1] https://example.com/source"
            ),
            model=model,
        )


class FakeAgent:
    def __init__(self, report):
        self.report = report
        self.loop = SimpleNamespace(
            provider=HallucinatingProvider(),
            model="fake",
        )

    async def run(self, goal, *, initial_variables=None, allowed_actions=None):
        return self.report


def report(success=True, status=AgentRunStatus.COMPLETED, action="web.compare", data=None):
    return AgentRunReport(
        goal="compare",
        status=status,
        success=success,
        final_message="Comparison completed." if success else "Comparison failed.",
        observations=(
            AgentObservation(
                iteration=1,
                action=action,
                arguments={},
                success=True,
                message="web evidence",
                data=data or {},
            ),
        ),
        variables={},
        iterations=2,
    )


@pytest.mark.asyncio
async def test_failed_run_never_becomes_confident_answer():
    item = report(
        success=False,
        status=AgentRunStatus.FAILED,
        action="web.search",
        data={
            "results": [
                {
                    "title": "Source",
                    "url": "https://example.com/source",
                    "snippet": "Retrieved evidence.",
                }
            ]
        },
    )
    answer, _ = await ConversationSession(FakeAgent(item)).ask("Verify the answer with sources")
    assert "did not complete successfully" in answer
    assert "cannot present a confident" in answer


@pytest.mark.asyncio
async def test_price_without_parsed_price_reports_insufficient_evidence():
    item = report(
        action="web.price_search",
        data={
            "results": [
                {
                    "title": "Store",
                    "url": "https://example.com/store",
                    "snippet": "Product page",
                    "price": None,
                }
            ]
        },
    )
    answer, _ = await ConversationSession(FakeAgent(item)).ask("Find the price")
    assert "could not verify enough reliable live evidence" in answer
    assert "No current listing with a parsed price" in answer


@pytest.mark.asyncio
async def test_hybrid_comparison_allows_model_knowledge_but_does_not_fabricate_source_urls():
    item = report(
        data={
            "results": [
                {
                    "title": "GPU comparison",
                    "url": "https://example.com/source",
                    "snippet": "RTX 3070 Ti and RX 6700 XT overview.",
                }
            ],
            "metadata": {
                "comparison": {
                    "RTX 3070 Ti": {
                        "evidence": [
                            {
                                "title": "RTX source one",
                                "url": "https://example.com/rtx1",
                                "snippet": "RTX 3070 Ti overview.",
                            },
                            {
                                "title": "RTX source two",
                                "url": "https://example.com/rtx2",
                                "snippet": "RTX 3070 Ti review.",
                            },
                        ],
                        "prices": [],
                    },
                    "RX 6700 XT": {
                        "evidence": [
                            {
                                "title": "RX source one",
                                "url": "https://example.com/rx1",
                                "snippet": "RX 6700 XT overview.",
                            },
                            {
                                "title": "RX source two",
                                "url": "https://example.com/rx2",
                                "snippet": "RX 6700 XT review.",
                            },
                        ],
                        "prices": [],
                    },
                }
            },
        },
    )
    answer, _ = await ConversationSession(FakeAgent(item)).ask("Compare them and give sources")
    # Hybrid mode deliberately allows stable model knowledge. Source URLs, however,
    # must still come from retrieved evidence.
    assert "https://example.com/source" in answer
