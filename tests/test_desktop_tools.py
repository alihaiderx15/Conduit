from __future__ import annotations

import pytest

from conduit.core.models import ToolCall
from conduit.desktop import DesktopController, Point, ScreenBounds
from conduit.desktop.tools import register_desktop_tools
from conduit.execution.executor import ToolExecutor
from conduit.execution.permissions import PermissionManager
from conduit.tools.models import PendingConfirmation, ToolRisk
from conduit.tools.registry import ToolRegistry


class FakeBackend:
    def __init__(self) -> None: self.calls=[]
    def screen_bounds(self): return ScreenBounds(800, 600)
    def mouse_position(self): return Point(10, 20)
    def move_to(self,*args): self.calls.append(("move",*args))
    def click(self,*args): self.calls.append(("click",*args))
    def write(self,*args): self.calls.append(("write",*args))
    def press(self,*args): self.calls.append(("press",*args))
    def hotkey(self,*args): self.calls.append(("hotkey",*args))
    def scroll(self,*args): self.calls.append(("scroll",*args))


def make_engine():
    registry=ToolRegistry(); backend=FakeBackend()
    register_desktop_tools(registry, DesktopController(backend))
    return registry, backend, ToolExecutor(registry, PermissionManager())


def test_registers_desktop_tools() -> None:
    registry, _, _ = make_engine()
    assert len(registry) == 8
    assert registry.get("click_screen").risk is ToolRisk.CONFIRM
    assert registry.get("get_screen_size").risk is ToolRisk.SAFE


@pytest.mark.asyncio
async def test_safe_information_tool_executes() -> None:
    _, _, executor = make_engine()
    result = await executor.execute(ToolCall("get_screen_size", {}))
    assert result.success is True
    assert result.data["width"] == 800


@pytest.mark.asyncio
async def test_desktop_action_waits_for_confirmation() -> None:
    _, backend, executor = make_engine()
    result = await executor.execute(ToolCall("click_screen", {"x": 20, "y": 30}))
    assert isinstance(result, PendingConfirmation)
    assert backend.calls == []


@pytest.mark.asyncio
async def test_confirmed_action_executes() -> None:
    _, backend, executor = make_engine()
    result = await executor.execute(ToolCall("click_screen", {"x": 20, "y": 30}), confirmed=True)
    assert result.success is True
    assert backend.calls[0][0] == "click"
