from __future__ import annotations

from collections import deque

import pytest

from conduit.approvals import ApprovalScope, TaskApprovalSession
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.providers.base import AIProvider


class ScriptedProvider(AIProvider):
    provider_id = "scripted-general-pc"

    def __init__(self, responses):
        self.responses = deque(responses)

    @property
    def capabilities(self):
        return ProviderCapabilities(chat=True, tools=True, vision=False)

    async def model_capabilities(self, model):
        return self.capabilities

    async def list_models(self):
        return ["scripted"]

    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(text=self.responses.popleft())


@pytest.mark.asyncio
async def test_general_pc_agent_exposes_unified_actions(tmp_path):
    target = tmp_path / "note.txt"
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Write the requested file","action":"files.write_text","arguments":{"path":"%s","text":"hello"}}' % str(target).replace('\\','\\\\'),
        '{"decision":"act","reason":"Verify existence","action":"files.exists","arguments":{"path":"%s"}}' % str(target).replace('\\','\\\\'),
        '{"decision":"finish","reason":"The file existence check succeeded","message":"done"}',
    ])
    scope = ApprovalScope(goal="write file", allowed_actions=frozenset({"files.write_text"}), allowed_path_roots=(tmp_path,))
    approval = TaskApprovalSession(scope); approval.approve()
    agent = await GeneralPCAgent.create(
        provider=provider,
        model="scripted",
        config=GeneralPCAgentConfig(headless_browser=True, enable_desktop_control=False),
        approval_session=approval,
    )
    try:
        report = await agent.run("Write and verify a file")
    finally:
        await agent.close()
    assert report.success is True
    assert target.read_text() == "hello"
    assert "files.write_text" in {item.name for item in agent.actions.all()}


@pytest.mark.asyncio
async def test_general_pc_agent_filters_vision_without_capability():
    provider = ScriptedProvider(['{"decision":"finish","reason":"No work needed","message":"done"}'])
    agent = await GeneralPCAgent.create(
        provider=provider,
        model="scripted",
        config=GeneralPCAgentConfig(headless_browser=True, enable_desktop_control=False),
    )
    try:
        names = {item.name for item in agent.loop.capabilities}
    finally:
        await agent.close()
    assert "vision.observe" not in names
    assert "desktop.click" not in names
    assert "files.exists" in names
