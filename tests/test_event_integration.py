from __future__ import annotations

from pathlib import Path

import pytest

from conduit.core.models import ToolCall
from conduit.desktop.controller import DesktopController
from conduit.desktop.models import Point, ScreenBounds
from conduit.events import EventBus, EventNames
from conduit.execution.executor import ToolExecutor
from conduit.observer.capture import DesktopCaptureService
from conduit.tools.models import ToolResult, ToolRisk
from conduit.tools.registry import ToolRegistry, tool


class FakeDesktopBackend:
    def screen_bounds(self) -> ScreenBounds:
        return ScreenBounds(1920, 1080)

    def mouse_position(self) -> Point:
        return Point(10, 20)

    def move_to(self, x: int, y: int, duration: float) -> None:
        pass

    def click(self, x: int, y: int, clicks: int, interval: float, button: str) -> None:
        pass

    def write(self, text: str, interval: float) -> None:
        pass

    def press(self, key: str, presses: int, interval: float) -> None:
        pass

    def hotkey(self, *keys: str) -> None:
        pass

    def scroll(self, amount: int) -> None:
        pass


class FakeCaptureBackend:
    def capture(self, destination: Path) -> tuple[int, int]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake")
        return (800, 600)


@pytest.mark.asyncio
async def test_executor_emits_started_and_completed_events() -> None:
    bus = EventBus()
    names: list[str] = []
    bus.subscribe("tool.*", lambda event: names.append(event.name))
    registry = ToolRegistry()

    @tool(registry, name="demo", description="Demo tool")
    def demo() -> ToolResult:
        return ToolResult(True, "done")

    executor = ToolExecutor(registry, event_bus=bus)
    result = await executor.execute(ToolCall("demo", {}, "call-1"))

    assert isinstance(result, ToolResult)
    assert names == [EventNames.TOOL_STARTED, EventNames.TOOL_COMPLETED]


@pytest.mark.asyncio
async def test_executor_emits_confirmation_event() -> None:
    bus = EventBus()
    names: list[str] = []
    bus.subscribe("permission.*", lambda event: names.append(event.name))
    registry = ToolRegistry()

    @tool(registry, name="protected", description="Protected", risk=ToolRisk.CONFIRM)
    def protected() -> ToolResult:
        return ToolResult(True, "done")

    executor = ToolExecutor(registry, event_bus=bus)
    await executor.execute(ToolCall("protected", {}, "call-2"))

    assert names == [EventNames.CONFIRMATION_REQUIRED]


def test_capture_service_emits_screen_event(tmp_path: Path) -> None:
    bus = EventBus()
    names: list[str] = []
    bus.subscribe("screen.*", lambda event: names.append(event.name))
    service = DesktopCaptureService(FakeCaptureBackend(), event_bus=bus)

    service.capture(tmp_path / "screen.png")

    assert names == [EventNames.SCREEN_CAPTURED]


def test_desktop_controller_emits_action_events() -> None:
    bus = EventBus()
    names: list[str] = []
    bus.subscribe("desktop.*", lambda event: names.append(event.name))
    controller = DesktopController(FakeDesktopBackend(), event_bus=bus)

    controller.move_mouse(100, 200)

    assert names == [
        EventNames.DESKTOP_ACTION_STARTED,
        EventNames.DESKTOP_ACTION_COMPLETED,
    ]
