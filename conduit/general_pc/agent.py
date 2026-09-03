"""High-level composition root for Conduit's General PC Agent v1."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from conduit.actions import UnifiedActionRegistry, UnifiedActionRouter, register_default_actions
from conduit.agent import PlanExecutor
from conduit.approvals import TaskApprovalSession
from conduit.browser import BrowserEngine
from conduit.desktop import DesktopController
from conduit.dynamic_agent import (
    DynamicAgentLoop,
    StructuredFileGoalVerifier,
    WindowsClipboardProcessVerifier,
    CompositeCompletionVerifier,
    RecentFileNotepadVerifier,
    ConversationalWebActionVerifier,
)
from conduit.events import EventBus
from conduit.execution import ToolExecutor
from conduit.memory import AgentMemoryBridge
from conduit.memory.models import MemoryCategory
from conduit.observer import DesktopObserver
from conduit.providers.base import AIProvider
from conduit.providers.recovery import ProviderRecoveryHandler, ProviderReplacement
from conduit.core.errors import ProviderError
from conduit.tools.builtin import registry as builtin_tool_registry
from conduit.tools.registry import ToolRegistry

from .models import GeneralPCAgentConfig


@dataclass(slots=True)
class GeneralPCAgent:
    """A composed dynamic agent that can select across all enabled PC actions."""

    provider: AIProvider
    model: str
    loop: DynamicAgentLoop
    browser: BrowserEngine
    events: EventBus
    actions: UnifiedActionRegistry
    router: UnifiedActionRouter
    provider_recovery_handler: ProviderRecoveryHandler | None = None

    @classmethod
    async def create(
        cls,
        *,
        provider: AIProvider,
        model: str,
        config: GeneralPCAgentConfig | None = None,
        event_bus: EventBus | None = None,
        tool_registry: ToolRegistry | None = None,
        approval_session: TaskApprovalSession | None = None,
        memory_bridge: AgentMemoryBridge | None = None,
        provider_recovery_handler: ProviderRecoveryHandler | None = None,
    ) -> "GeneralPCAgent":
        """Build every backend required by the general PC agent."""
        config = config or GeneralPCAgentConfig()
        events = event_bus or EventBus()
        tools_registry = tool_registry or builtin_tool_registry
        actions = register_default_actions(UnifiedActionRegistry(tools_registry))

        model_caps = await provider.model_capabilities(model)
        observer = None
        if config.enable_vision_when_available and model_caps.vision:
            observer = DesktopObserver(provider, model=model)

        desktop = DesktopController(event_bus=events) if config.enable_desktop_control else None
        browser = BrowserEngine(
            event_bus=events,
            headless=config.headless_browser,
            downloads_dir=config.downloads_dir,
            action_timeout_ms=config.browser_timeout_ms,
        )
        tool_executor = ToolExecutor(tools_registry, event_bus=events)

        # Persist concise operational state for system/app actions so follow-up
        # requests can use Conduit's existing local memory bridge. This records
        # outcomes, never executable instructions.
        if memory_bridge is not None:
            async def remember_system_tool_event(event) -> None:
                payload = dict(event.payload)
                tool_name = str(payload.get("tool_name", "")).strip()
                if not tool_name.startswith("system.") or not bool(payload.get("success")):
                    return
                data = payload.get("data")
                if not isinstance(data, dict):
                    data = {}
                manager = memory_bridge.manager
                try:
                    manager.remember(
                        "last_system_action",
                        tool_name,
                        category=MemoryCategory.TASK,
                        importance=0.65,
                        source="system_action",
                        metadata={"tool": tool_name},
                    )

                    if tool_name == "system.open_app":
                        name = str(data.get("name") or data.get("requested") or "").strip()
                        if name:
                            manager.remember(
                                "last_opened_app", name, category=MemoryCategory.TASK,
                                importance=0.8, source="system_action",
                                metadata={"tool": tool_name},
                            )
                    elif tool_name == "system.open_apps":
                        opened = data.get("opened", [])
                        names = [str(x.get("name") or x.get("requested")) for x in opened if isinstance(x, dict)]
                        if names:
                            manager.remember(
                                "last_opened_apps", ", ".join(names), category=MemoryCategory.TASK,
                                importance=0.8, source="system_action", metadata={"tool": tool_name},
                            )
                    elif tool_name == "system.close_app":
                        name = str(data.get("requested") or "").strip()
                        if name:
                            manager.remember(
                                "last_closed_app", name, category=MemoryCategory.TASK,
                                importance=0.75, source="system_action", metadata={"tool": tool_name},
                            )
                    elif tool_name == "system.close_apps":
                        rows = data.get("results", [])
                        names = [str(x.get("requested")) for x in rows if isinstance(x, dict) and x.get("requested")]
                        if names:
                            manager.remember(
                                "last_closed_apps", ", ".join(names), category=MemoryCategory.TASK,
                                importance=0.75, source="system_action", metadata={"tool": tool_name},
                            )
                except Exception:
                    # Operational memory must never make a successful system
                    # action fail. Memory remains best-effort and local.
                    return

            events.subscribe("tool.completed", remember_system_tool_event)
        router = UnifiedActionRouter(
            browser=browser,
            tools=tool_executor,
            desktop=desktop,
            observer=observer,
        )
        executor = PlanExecutor(
            browser=browser,
            tools=tool_executor,
            event_bus=events,
            default_retries=0,
            action_router=router,
            approval_session=approval_session,
            task_intent_consent=True,
        )

        capabilities = tuple(
            item for item in actions.planning_capabilities()
            if _capability_is_available(
                item.name,
                desktop_enabled=desktop is not None,
                vision_enabled=observer is not None,
            )
        )
        loop_ref: dict[str, DynamicAgentLoop] = {}

        async def recover_provider(exc, current_provider, current_model):
            if provider_recovery_handler is None:
                return None
            replacement = await provider_recovery_handler(exc, current_provider, current_model)
            if replacement is None:
                return None
            new_caps = await replacement.provider.model_capabilities(replacement.model)
            router.observer = (
                DesktopObserver(replacement.provider, model=replacement.model)
                if config.enable_vision_when_available and new_caps.vision else None
            )
            refreshed = tuple(
                item for item in actions.planning_capabilities()
                if _capability_is_available(
                    item.name,
                    desktop_enabled=desktop is not None,
                    vision_enabled=router.observer is not None,
                )
            )
            if "loop" in loop_ref:
                loop_ref["loop"].set_capabilities(refreshed)
            return replacement

        loop = DynamicAgentLoop(
            provider=provider,
            model=model,
            executor=executor,
            capabilities=capabilities,
            event_bus=events,
            memory_bridge=memory_bridge,
            max_iterations=config.max_iterations,
            max_decision_attempts=config.max_decision_attempts,
            max_consecutive_failures=config.max_consecutive_failures,
            prevent_blind_retries=config.prevent_blind_retries,
            provider_timeout_seconds=config.provider_timeout_seconds,
            completion_verifier=(
                CompositeCompletionVerifier(
                    StructuredFileGoalVerifier(),
                    WindowsClipboardProcessVerifier(),
                    RecentFileNotepadVerifier(),
                    ConversationalWebActionVerifier(),
                )
                if config.enable_deterministic_completion
                else None
            ),
            provider_recovery_handler=recover_provider if provider_recovery_handler else None,
        )
        loop_ref["loop"] = loop
        await events.emit(
            "general_pc.ready",
            source="GeneralPCAgent",
            payload={
                "provider": provider.provider_id,
                "model": model,
                "actions": len(capabilities),
                "vision": observer is not None,
                "desktop": desktop is not None,
            },
        )
        return cls(provider, model, loop, browser, events, actions, router, provider_recovery_handler)

    @property
    def tools(self) -> ToolExecutor:
        """Expose the composed tool executor for direct deterministic actions."""
        return self.router.tools

    async def run(
        self,
        goal: str,
        *,
        initial_variables: dict[str, Any] | None = None,
        allowed_actions: set[str] | None = None,
    ):
        """Run one natural-language PC goal through the dynamic loop."""
        await self.events.emit("general_pc.started", source="GeneralPCAgent", payload={"goal": goal})
        report = await self.loop.run(
            goal,
            initial_variables=initial_variables,
            allowed_actions=allowed_actions,
        )
        # A recovery handler may have hot-swapped the provider/model mid-run.
        self.provider = self.loop.provider
        self.model = self.loop.model
        await self.events.emit(
            "general_pc.completed",
            source="GeneralPCAgent",
            payload={"goal": goal, "success": report.success, "status": report.status.value},
        )
        return report

    async def recover_provider_error(self, error: ProviderError) -> bool:
        """Recover provider failures raised outside the dynamic agent loop (e.g. vision)."""
        if self.provider_recovery_handler is None:
            return False
        current = self.loop.provider
        current_model = self.loop.model
        replacement = await self.provider_recovery_handler(error, current, current_model)
        if replacement is None:
            return False
        await self.switch_provider(
            replacement.provider,
            replacement.model,
            reason=replacement.reason or "Recovered from provider failure.",
        )
        return True

    async def switch_provider(
        self,
        provider: AIProvider,
        model: str,
        *,
        reason: str = "User requested a provider switch.",
    ) -> None:
        """Hot-swap the conversational agent while preserving chat/session state."""

        model = model.strip()
        if not model:
            raise ValueError("A model is required for provider switching.")

        capabilities = await provider.model_capabilities(model)
        observer = (
            DesktopObserver(provider, model=model)
            if capabilities.vision
            else None
        )
        refreshed = tuple(
            item
            for item in self.actions.planning_capabilities()
            if _capability_is_available(
                item.name,
                desktop_enabled=self.router.desktop is not None,
                vision_enabled=observer is not None,
            )
        )

        old_provider = self.loop.provider
        old_provider_id = old_provider.provider_id
        old_model = self.loop.model

        self.router.observer = observer
        self.loop.provider = provider
        self.loop.model = model
        self.loop.set_capabilities(refreshed)
        self.provider = provider
        self.model = model

        await self.events.emit(
            "agent.provider.switched",
            source="GeneralPCAgent",
            payload={
                "from_provider": old_provider_id,
                "from_model": old_model,
                "to_provider": provider.provider_id,
                "model": model,
                "reason": reason,
                "vision": observer is not None,
                "actions": len(refreshed),
            },
        )

        if old_provider is not provider:
            await old_provider.close()

    async def close(self) -> None:
        """Release browser and provider resources."""
        await self.browser.close()
        # The loop owns the currently active provider after any hot-swap.
        await self.loop.provider.close()


def _capability_is_available(name: str, *, desktop_enabled: bool, vision_enabled: bool) -> bool:
    if name.startswith("vision."):
        return vision_enabled
    if name == "desktop.click":
        return desktop_enabled and vision_enabled
    if name.startswith("desktop."):
        return desktop_enabled
    return True
