"""Execute validated plans across Conduit's engines."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from conduit.browser import BrowserEngine, BrowserTarget, TargetKind
from conduit.approvals import TaskApprovalSession
from conduit.actions import UnifiedActionRouter
from conduit.core.models import ToolCall
from conduit.capabilities import YouTubeAgent
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.planning import PlanStep, StepCapability, TaskPlan

from .models import PlanExecutionReport, StepExecutionResult, StepStatus

ConfirmationHandler = Callable[[PlanStep], bool | Awaitable[bool]]

# These actions can irreversibly remove data or discard unsaved work.
# They still require a separate explicit confirmation.
_DESTRUCTIVE_ACTIONS = {
    "files.delete",
    "system.close_app",
}


class PlanExecutor:
    """Run a task plan in dependency order with retries and event reporting."""

    def __init__(
        self,
        *,
        browser: BrowserEngine,
        tools: ToolExecutor,
        event_bus: EventBus | None = None,
        confirmation_handler: ConfirmationHandler | None = None,
        default_retries: int = 1,
        action_router: UnifiedActionRouter | None = None,
        approval_session: TaskApprovalSession | None = None,
        task_intent_consent: bool = False,
    ) -> None:
        self.browser = browser
        self.tools = tools
        self.events = event_bus
        self.confirmation_handler = confirmation_handler
        self.default_retries = max(0, default_retries)
        self.youtube = YouTubeAgent(browser, event_bus=event_bus)
        self.action_router = action_router
        self.approval_session = approval_session
        self.task_intent_consent = bool(task_intent_consent)

    async def execute_step(self, step: PlanStep) -> StepExecutionResult:
        """Execute one validated step for iterative agents and integrations."""
        if step.requires_confirmation and not await self._confirm(step):
            result = StepExecutionResult(step, StepStatus.CANCELLED, "The user did not approve this step.")
            await self._emit_step("execution.step.cancelled", result)
            return result
        return await self._execute_with_retry(step)

    async def execute(self, plan: TaskPlan) -> PlanExecutionReport:
        await self._emit("execution.started", {"goal": plan.goal, "steps": len(plan.steps)})
        results: list[StepExecutionResult] = []
        statuses: dict[str, StepStatus] = {}

        for step in plan.steps:
            failed_dependencies = [
                dependency
                for dependency in step.depends_on
                if statuses.get(dependency) is not StepStatus.COMPLETED
            ]
            if failed_dependencies:
                result = StepExecutionResult(
                    step,
                    StepStatus.BLOCKED,
                    f"Blocked by incomplete dependencies: {', '.join(failed_dependencies)}.",
                )
                results.append(result)
                statuses[step.id] = result.status
                await self._emit_step("execution.step.blocked", result)
                continue

            if step.requires_confirmation and not await self._confirm(step):
                result = StepExecutionResult(step, StepStatus.CANCELLED, "The user did not approve this step.")
                results.append(result)
                statuses[step.id] = result.status
                await self._emit_step("execution.step.cancelled", result)
                continue

            result = await self._execute_with_retry(step)
            results.append(result)
            statuses[step.id] = result.status
            if result.status is StepStatus.FAILED:
                # Remaining dependent steps will become BLOCKED. Independent steps may continue.
                continue

        success = all(item.status is StepStatus.COMPLETED for item in results)
        message = "The plan completed successfully." if success else "The plan did not complete successfully."
        report = PlanExecutionReport(plan, success, tuple(results), message)
        await self._emit(
            "execution.completed" if success else "execution.failed",
            {"goal": plan.goal, "success": success, "completed": len(report.completed_steps)},
        )
        return report

    async def _execute_with_retry(self, step: PlanStep) -> StepExecutionResult:
        attempts = self.default_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            await self._emit("execution.step.started", {"step_id": step.id, "action": step.action, "attempt": attempt})
            try:
                data, message = await self._dispatch(step)
                result = StepExecutionResult(step, StepStatus.COMPLETED, message, data, attempt)
                await self._emit_step("execution.step.completed", result)
                return result
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await self._emit(
                        "execution.step.retrying",
                        {"step_id": step.id, "action": step.action, "attempt": attempt, "error": str(exc)},
                    )
                    await asyncio.sleep(0.4)
        assert last_error is not None
        result = StepExecutionResult(
            step,
            StepStatus.FAILED,
            str(last_error),
            attempts=attempts,
            error_type=type(last_error).__name__,
        )
        await self._emit_step("execution.step.failed", result)
        return result

    async def _dispatch(self, step: PlanStep) -> tuple[dict[str, Any], str]:
        if self.action_router is not None:
            outcome = await self.action_router.execute(step)
            if not outcome.success:
                raise RuntimeError(outcome.message)
            return dict(outcome.data), outcome.message

        arguments = dict(step.arguments)
        action = step.action

        if step.capability is StepCapability.TOOL:
            outcome = await self.tools.execute(ToolCall(action, arguments), confirmed=True)
            if not hasattr(outcome, "success") or not outcome.success:
                raise RuntimeError(getattr(outcome, "message", f"Tool {action!r} did not complete."))
            return dict(outcome.data), outcome.message

        if action == "browser.start":
            result = await self.browser.start()
            return {}, result.message
        if action == "browser.launch_profile":
            result = await self.browser.launch_profile(
                str(arguments.get("browser", "")),
                profile=str(arguments.get("profile", "Default")),
                private=bool(arguments.get("private", False)),
                url=str(arguments.get("url", "about:blank")),
            )
            return dict(result.data), result.message
        if action == "browser.attach_existing":
            result = await self.browser.attach_existing(
                str(arguments.get("browser", "")),
                endpoint=str(arguments.get("endpoint", "")),
            )
            return dict(result.data), result.message
        if action == "browser.list_sessions":
            result = await self.browser.list_sessions()
            return dict(result.data), result.message
        if action == "browser.switch_session":
            result = await self.browser.switch_session(str(arguments["session_id"]))
            return dict(result.data), result.message
        if action == "browser.use_default_profile":
            result = await self.browser.use_default_profile(
                browser=str(arguments.get("browser", "")),
                url=str(arguments.get("url", "about:blank")),
                private=bool(arguments.get("private", False)),
            )
            return dict(result.data), result.message
        if action == "browser.installed":
            result = await self.browser.installed()
            return dict(result.data), result.message
        if action == "browser.new_tab":
            result = await self.browser.new_tab(str(arguments.get("url", "about:blank")))
            return {"url": result.state.url if result.state else ""}, result.message
        if action == "browser.close_tab":
            result = await self.browser.close_tab(arguments.get("tab"))
            return dict(result.data), result.message
        if action == "browser.close_all_tabs":
            result = await self.browser.close_all_tabs()
            return dict(result.data), result.message
        if action == "browser.list_tabs":
            result = await self.browser.list_tabs()
            return dict(result.data), result.message
        if action == "browser.switch_tab":
            result = await self.browser.switch_tab(arguments["tab"])
            return dict(result.data), result.message
        if action == "browser.back":
            result = await self.browser.back()
            return dict(result.data), result.message
        if action == "browser.forward":
            result = await self.browser.forward()
            return dict(result.data), result.message
        if action == "browser.reload":
            result = await self.browser.reload()
            return dict(result.data), result.message
        if action == "browser.screenshot":
            result = await self.browser.screenshot(str(arguments.get("path", "")))
            return dict(result.data), result.message
        if action == "browser.download":
            target = self._target(arguments)
            result = await self.browser.download_active(
                target,
                filename=str(arguments["filename"]) if arguments.get("filename") else None,
            )
            return dict(result.data), result.message
        if action == "browser.goto":
            result = await self.browser.goto(str(arguments["url"]))
            return {"url": result.state.url if result.state else ""}, result.message
        if action == "browser.read_page":
            state = await self.browser.state()
            return {"title": state.title, "url": state.url, "visible_text": state.visible_text}, "Read the current page."
        if action == "browser.fill":
            target = self._target(arguments)
            result = await self.browser.fill(target, str(arguments["text"]))
            return {}, result.message
        if action == "browser.click":
            target = self._target(arguments)
            result = await self.browser.click(target)
            return {"url": result.state.url if result.state else ""}, result.message
        if action == "browser.press":
            key = str(arguments["key"])
            if "kind" in arguments and "value" in arguments:
                result = await self.browser.press(self._target(arguments), key)
            else:
                result = await self.browser.press_page(key)
            return {}, result.message
        if action == "browser.scroll":
            result = await self.browser.scroll(delta_y=int(arguments.get("delta_y", 700)))
            return {}, result.message
        if action == "youtube.play_latest_upload":
            result = await self.youtube.play_latest_upload(str(arguments["channel"]))
            return {
                "channel": result.channel,
                "video_title": result.video_title,
                "video_url": result.video_url,
                "verified": result.verified,
            }, f"Opened the latest upload from {result.channel}: {result.video_title}."

        raise ValueError(f"Unsupported plan action: {action}")

    async def _confirm(self, step: PlanStep) -> bool:
        # An explicitly supplied approval session is intentionally strict.
        if self.approval_session is not None:
            await self._emit(
                "execution.confirmation.required",
                {"step_id": step.id, "title": step.title, "action": step.action},
            )
            approved, reason = self.approval_session.authorize(step)
            await self._emit(
                "execution.confirmation.scope_evaluated",
                {
                    "step_id": step.id,
                    "action": step.action,
                    "approved": approved,
                    "reason": reason,
                },
            )
            if approved:
                return True
            if self.confirmation_handler is None:
                return False

        # General PC Agent enables this mode: the user's natural-language task
        # authorizes ordinary, reversible actions needed to complete that task.
        if self.task_intent_consent and step.action not in _DESTRUCTIVE_ACTIONS:
            await self._emit(
                "execution.task_intent.authorized",
                {
                    "step_id": step.id,
                    "action": step.action,
                    "reason": "Authorized by the user's stated task.",
                },
            )
            return True

        await self._emit(
            "execution.confirmation.required",
            {"step_id": step.id, "title": step.title, "action": step.action},
        )
        if self.confirmation_handler is None:
            return False
        decision = self.confirmation_handler(step)
        if isinstance(decision, Awaitable):
            decision = await decision
        await self._emit(
            "execution.confirmation.resolved",
            {"step_id": step.id, "approved": bool(decision)},
        )
        return bool(decision)

    @staticmethod
    def _target(arguments: dict[str, Any]) -> BrowserTarget:
        return BrowserTarget(
            kind=TargetKind(str(arguments["kind"])),
            value=str(arguments["value"]),
            name=str(arguments["name"]) if arguments.get("name") is not None else None,
            exact=bool(arguments.get("exact", False)),
        )

    async def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self.events is not None:
            await self.events.emit(name, source="PlanExecutor", payload=payload)

    async def _emit_step(self, name: str, result: StepExecutionResult) -> None:
        await self._emit(
            name,
            {
                "step_id": result.step.id,
                "action": result.step.action,
                "status": result.status.value,
                "message": result.message,
                "attempts": result.attempts,
            },
        )
