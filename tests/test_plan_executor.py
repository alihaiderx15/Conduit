from __future__ import annotations

from dataclasses import dataclass

import pytest

from conduit.agent import PlanExecutor, StepStatus
from conduit.browser.models import BrowserActionResult, BrowserState
from conduit.core.models import ToolCall
from conduit.planning import PlanStep, StepCapability, TaskPlan
from conduit.tools.models import ToolResult


STATE = BrowserState("Test", "https://example.test", "hello", 1280, 720)


class FakeBrowser:
    def __init__(self):
        self.is_started = False
        self.calls = []

    async def start(self):
        self.is_started = True
        self.calls.append(("start", {}))
        return BrowserActionResult(True, "start", "started", STATE)

    async def goto(self, url):
        self.calls.append(("goto", {"url": url}))
        return BrowserActionResult(True, "goto", "opened", STATE)

    async def state(self):
        return STATE


class FakeTools:
    def __init__(self, success=True):
        self.calls = []
        self.success = success

    async def execute(self, call: ToolCall, *, confirmed=False):
        self.calls.append((call, confirmed))
        return ToolResult(self.success, "tool done" if self.success else "tool failed")


@pytest.mark.asyncio
async def test_executes_browser_steps_in_order():
    browser = FakeBrowser()
    tools = FakeTools()
    plan = TaskPlan(
        "Open example",
        "test",
        (
            PlanStep("s1", "Start", StepCapability.BROWSER, "browser.start"),
            PlanStep("s2", "Go", StepCapability.BROWSER, "browser.goto", {"url": "example.test"}, ("s1",)),
        ),
    )
    report = await PlanExecutor(browser=browser, tools=tools, default_retries=0).execute(plan)
    assert report.success
    assert [item.status for item in report.results] == [StepStatus.COMPLETED, StepStatus.COMPLETED]
    assert browser.calls == [("start", {}), ("goto", {"url": "example.test"})]


@pytest.mark.asyncio
async def test_confirmation_denial_cancels_step():
    plan = TaskPlan(
        "Create folder",
        "test",
        (PlanStep("s1", "Create", StepCapability.TOOL, "create_folder", {"path": "x"}, requires_confirmation=True),),
    )
    report = await PlanExecutor(browser=FakeBrowser(), tools=FakeTools(), default_retries=0).execute(plan)
    assert not report.success
    assert report.results[0].status is StepStatus.CANCELLED


@pytest.mark.asyncio
async def test_failed_dependency_blocks_later_step():
    plan = TaskPlan(
        "Fail",
        "test",
        (
            PlanStep("s1", "Bad", StepCapability.TOOL, "bad_tool"),
            PlanStep("s2", "Later", StepCapability.BROWSER, "browser.start", depends_on=("s1",)),
        ),
    )
    report = await PlanExecutor(browser=FakeBrowser(), tools=FakeTools(success=False), default_retries=0).execute(plan)
    assert [item.status for item in report.results] == [StepStatus.FAILED, StepStatus.BLOCKED]
