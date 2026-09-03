from __future__ import annotations

from collections import deque

import pytest

from conduit.agent import StepExecutionResult, StepStatus
from conduit.browser.models import BrowserState
from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.dynamic_agent import AgentRunStatus, DynamicAgentLoop
from conduit.providers.base import AIProvider


class ScriptedProvider(AIProvider):
    provider_id = "scripted"

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
    def __init__(self):
        self.is_started = False
        self.current_state = BrowserState("", "about:blank", "", 1280, 720)

    async def state(self, *, max_text_characters=8000):
        return self.current_state


class FakeExecutor:
    def __init__(self, outcomes):
        self.browser = FakeBrowser()
        self.outcomes = deque(outcomes)
        self.steps = []

    async def execute_step(self, step):
        self.steps.append(step)
        success, message, data = self.outcomes.popleft()
        if step.action == "browser.start" and success:
            self.browser.is_started = True
        if data.get("state"):
            self.browser.current_state = data["state"]
            data = {k: v for k, v in data.items() if k != "state"}
        return StepExecutionResult(
            step,
            StepStatus.COMPLETED if success else StepStatus.FAILED,
            message,
            data,
            error_type=None if success else "RuntimeError",
        )


@pytest.mark.asyncio
async def test_iterates_actions_then_finishes_with_evidence():
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Start browser","action":"browser.start","arguments":{},"expected_outcome":"ready"}',
        '{"decision":"act","reason":"Open page","action":"browser.goto","arguments":{"url":"https://example.test"},"expected_outcome":"page loaded"}',
        '{"decision":"finish","reason":"The URL observation proves completion","message":"The page is open."}',
    ])
    state = BrowserState("Example", "https://example.test", "Example page", 1280, 720)
    executor = FakeExecutor([
        (True, "started", {}),
        (True, "opened", {"url": "https://example.test", "state": state}),
    ])
    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=executor,
        max_iterations=5,
    ).run("Open example.test")

    assert report.success
    assert report.status is AgentRunStatus.COMPLETED
    assert [step.action for step in executor.steps] == ["browser.start", "browser.goto"]
    assert len(report.observations) == 2
    assert "example.test" in provider.prompts[-1][1].content


@pytest.mark.asyncio
async def test_can_recover_after_failed_action():
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Try selector","action":"browser.click","arguments":{"kind":"text","value":"Missing"},"expected_outcome":"clicked"}',
        '{"decision":"act","reason":"Inspect page after failure","action":"browser.read_page","arguments":{},"expected_outcome":"page details"}',
        '{"decision":"finish","reason":"Inspection supplied the needed result","message":"Recovered."}',
    ])
    executor = FakeExecutor([
        (False, "target missing", {}),
        (True, "Read the current page.", {"visible_text": "Recovered content"}),
    ])
    executor.browser.is_started = True
    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=executor,
        max_iterations=5,
    ).run("Recover")

    assert report.success
    assert report.observations[0].success is False
    assert report.observations[1].success is True


@pytest.mark.asyncio
async def test_stops_after_consecutive_failures():
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Try one","action":"browser.start","arguments":{}}',
        '{"decision":"act","reason":"Try two","action":"browser.start","arguments":{}}',
    ])
    executor = FakeExecutor([(False, "failed 1", {}), (False, "failed 2", {})])
    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=executor,
        max_iterations=5,
        max_consecutive_failures=2,
    ).run("Impossible")
    assert not report.success
    assert report.status is AgentRunStatus.FAILED


@pytest.mark.asyncio
async def test_returns_question_without_executing():
    provider = ScriptedProvider([
        '{"decision":"ask_user","reason":"Missing destination","message":"Which folder should I use?"}'
    ])
    executor = FakeExecutor([])
    report = await DynamicAgentLoop(provider=provider, model="test", executor=executor).run("Create it")
    assert report.status is AgentRunStatus.WAITING_FOR_USER
    assert report.pending_question == "Which folder should I use?"
    assert executor.steps == []


@pytest.mark.asyncio
async def test_captures_result_and_reuses_it_in_later_action():
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Read current page","action":"browser.read_page","arguments":{},'
        '"save_as":{"discovered_url":"data.url"}}',
        '{"decision":"act","reason":"Reuse discovered URL","action":"browser.goto",'
        '"arguments":{"url":"{{discovered_url}}"},"expected_outcome":"same page loaded"}',
        '{"decision":"finish","reason":"The reused URL was opened","message":"Variable reuse worked."}',
    ])
    state = BrowserState("Example", "https://example.test/discovered", "Example", 1280, 720)
    executor = FakeExecutor([
        (True, "Read the current page.", {"url": state.url, "title": state.title}),
        (True, "Opened", {"url": state.url, "state": state}),
    ])
    executor.browser.is_started = True

    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=executor,
        max_iterations=5,
    ).run("Read and reopen the current URL")

    assert report.success
    assert executor.steps[1].arguments["url"] == "https://example.test/discovered"
    assert report.variables["discovered_url"] == "https://example.test/discovered"


@pytest.mark.asyncio
async def test_unknown_reference_becomes_observation_and_allows_recovery():
    provider = ScriptedProvider([
        '{"decision":"act","reason":"Try missing value","action":"browser.goto",'
        '"arguments":{"url":"{{missing_url}}"}}',
        '{"decision":"act","reason":"Use a direct URL instead","action":"browser.goto",'
        '"arguments":{"url":"https://example.test"}}',
        '{"decision":"finish","reason":"The direct URL succeeded","message":"Recovered."}',
    ])
    state = BrowserState("Example", "https://example.test", "Example", 1280, 720)
    executor = FakeExecutor([(True, "Opened", {"url": state.url, "state": state})])
    executor.browser.is_started = True

    report = await DynamicAgentLoop(
        provider=provider,
        model="test",
        executor=executor,
        max_iterations=5,
    ).run("Open example")

    assert report.success
    assert report.observations[0].success is False
    assert report.observations[0].error_type == "VariableResolutionError"
    assert len(executor.steps) == 1
