from __future__ import annotations

from collections import deque

import pytest

from conduit.agent import StepExecutionResult, StepStatus
from conduit.browser.models import BrowserState
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.dynamic_agent import DynamicAgentLoop
from conduit.memory import (
    AgentMemoryBridge,
    MemoryCategory,
    MemoryManager,
    MemoryProposal,
    MemoryWriteMode,
)
from conduit.providers.base import AIProvider


class PromptCheckingProvider(AIProvider):
    provider_id = "memory-test"

    def __init__(self, responses):
        self.responses = deque(ProviderResponse(text=item) for item in responses)
        self.prompts = []

    @property
    def capabilities(self):
        return ProviderCapabilities()

    async def list_models(self):
        return ["test"]

    async def chat(self, messages, *, model, tools=()):
        self.prompts.append(tuple(messages))
        return self.responses.popleft()


class FakeBrowser:
    is_started = False

    async def state(self, *, max_text_characters=8000):
        return BrowserState("", "about:blank", "", 1280, 720)


class FakeExecutor:
    def __init__(self):
        self.browser = FakeBrowser()

    async def execute_step(self, step):
        return StepExecutionResult(step, StepStatus.COMPLETED, "ok", {})


def test_bridge_retrieves_relevant_memories_and_auto_saves_safe_proposal(tmp_path):
    manager = MemoryManager(tmp_path / "memory.db")
    manager.remember(
        "preferred_browser",
        "Opera",
        category=MemoryCategory.PREFERENCE,
        importance=0.9,
    )
    bridge = AgentMemoryBridge(manager, write_mode=MemoryWriteMode.AUTO_SAFE)

    injection = bridge.retrieve("Open my preferred browser")
    assert any(record.key == "preferred_browser" for record in injection.records)
    assert "Opera" in injection.prompt_text

    results = bridge.handle_proposals([
        MemoryProposal(
            key="preferred_provider",
            value="Ollama",
            category=MemoryCategory.PREFERENCE,
            importance=0.8,
            reason="User selected it repeatedly.",
        )
    ])
    assert results[0].saved
    assert manager.repository.get_memory(MemoryCategory.PREFERENCE, "preferred_provider") is not None
    manager.close()


def test_propose_only_does_not_write(tmp_path):
    manager = MemoryManager(tmp_path / "memory.db")
    bridge = AgentMemoryBridge(manager, write_mode=MemoryWriteMode.PROPOSE_ONLY)
    result = bridge.handle_proposals([
        MemoryProposal("favorite_editor", "VS Code", MemoryCategory.PREFERENCE)
    ])[0]
    assert not result.saved
    assert "approval" in result.reason.lower()
    assert manager.repository.get_memory(MemoryCategory.PREFERENCE, "favorite_editor") is None
    manager.close()


@pytest.mark.asyncio
async def test_dynamic_agent_injects_memory_and_saves_safe_proposal(tmp_path):
    manager = MemoryManager(tmp_path / "memory.db")
    manager.remember(
        "preferred_test_phrase",
        "Remembered by Conduit",
        category=MemoryCategory.PREFERENCE,
        importance=1.0,
    )
    bridge = AgentMemoryBridge(manager, write_mode=MemoryWriteMode.AUTO_SAFE)
    provider = PromptCheckingProvider([
        '{"decision":"finish","reason":"The remembered preference answers the goal",'
        '"message":"Used the remembered phrase.",'
        '"memory_proposals":[{"key":"memory_integration_status","value":"passed",'
        '"category":"fact","importance":0.7,"reason":"Verified integration test result"}]}',
    ])
    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=FakeExecutor(),
        memory_bridge=bridge,
    ).run("What is my preferred test phrase?")

    prompt = provider.prompts[0][1].content
    assert "Remembered by Conduit" in prompt
    assert report.success
    assert report.relevant_memories
    assert report.memory_proposal_results[0].saved
    assert manager.repository.get_memory(MemoryCategory.FACT, "memory_integration_status") is not None
    manager.close()
