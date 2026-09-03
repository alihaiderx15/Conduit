from __future__ import annotations
from collections import deque
import pytest
from conduit.agent import PlanExecutor
from conduit.browser import BrowserEngine
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.dynamic_agent import DynamicAgentLoop
from conduit.execution import ToolExecutor
from conduit.planning import PlanningCapability, StepCapability
from conduit.providers.base import AIProvider
from conduit.tools import ToolRegistry, tool, ToolResult

class P(AIProvider):
    provider_id='p'
    def __init__(self): self.q=deque([
        '{"decision":"act","reason":"try","action":"always_fail","arguments":{}}',
        '{"decision":"act","reason":"retry same","action":"always_fail","arguments":{}}',
        '{"decision":"fail","reason":"cannot continue","message":"stopped"}',
    ])
    @property
    def capabilities(self): return ProviderCapabilities(chat=True)
    async def list_models(self): return ['m']
    async def chat(self,messages,*,model,tools=()): return ProviderResponse(text=self.q.popleft())

@pytest.mark.asyncio
async def test_identical_failed_action_is_blocked():
    reg=ToolRegistry()
    @tool(reg,name='always_fail',description='fail')
    def fail(): return ToolResult(False,'no')
    ex=PlanExecutor(browser=BrowserEngine(headless=True), tools=ToolExecutor(reg), default_retries=0)
    cap=(PlanningCapability('always_fail',StepCapability.TOOL,'fail',{},False),)
    agent=DynamicAgentLoop(provider=P(),model='m',executor=ex,capabilities=cap,max_iterations=4,prevent_blind_retries=True)
    report=await agent.run('test')
    assert any(o.error_type=='BlindRetryBlocked' for o in report.observations)
