"""Desktop controller tools registered with Conduit's tool engine."""
from __future__ import annotations

from conduit.tools.models import ToolResult, ToolRisk
from conduit.tools.registry import ToolRegistry, tool

from .controller import DesktopController


def register_desktop_tools(registry: ToolRegistry, controller: DesktopController | None = None) -> None:
    """Register controlled mouse and keyboard tools into a registry."""
    desktop = controller or DesktopController()

    @tool(
        registry,
        name="get_screen_size",
        description="Return the current primary screen dimensions in pixels.",
    )
    def get_screen_size() -> ToolResult:
        bounds = desktop.screen_bounds()
        return ToolResult(True, f"The screen is {bounds.width} by {bounds.height} pixels.", {"width": bounds.width, "height": bounds.height})

    @tool(
        registry,
        name="get_mouse_position",
        description="Return the current mouse pointer coordinates.",
    )
    def get_mouse_position() -> ToolResult:
        point = desktop.mouse_position()
        return ToolResult(True, f"The pointer is at ({point.x}, {point.y}).", {"x": point.x, "y": point.y})

    @tool(
        registry,
        name="move_mouse",
        description="Move the mouse pointer to exact screen coordinates.",
        parameters={"type": "object", "properties": {"x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}}, "required": ["x", "y"]},
        risk=ToolRisk.CONFIRM,
    )
    def move_mouse(x: int, y: int) -> ToolResult:
        result = desktop.move_mouse(x, y)
        return ToolResult(result.success, result.message, result.data)

    @tool(
        registry,
        name="click_screen",
        description="Click exact screen coordinates using the requested mouse button.",
        parameters={"type": "object", "properties": {"x": {"type": "integer", "minimum": 0}, "y": {"type": "integer", "minimum": 0}, "button": {"type": "string", "enum": ["left", "middle", "right"]}, "clicks": {"type": "integer", "minimum": 1, "maximum": 3}}, "required": ["x", "y"]},
        risk=ToolRisk.CONFIRM,
    )
    def click_screen(x: int, y: int, button: str = "left", clicks: int = 1) -> ToolResult:
        result = desktop.click(x, y, button=button, clicks=clicks)
        return ToolResult(result.success, result.message, result.data)

    @tool(
        registry,
        name="type_text",
        description="Type text into the currently focused desktop application.",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        risk=ToolRisk.CONFIRM,
    )
    def type_text(text: str) -> ToolResult:
        result = desktop.type_text(text)
        return ToolResult(result.success, result.message, result.data)

    @tool(
        registry,
        name="press_key",
        description="Press one keyboard key one or more times.",
        parameters={"type": "object", "properties": {"key": {"type": "string"}, "presses": {"type": "integer", "minimum": 1, "maximum": 20}}, "required": ["key"]},
        risk=ToolRisk.CONFIRM,
    )
    def press_key(key: str, presses: int = 1) -> ToolResult:
        result = desktop.press_key(key, presses)
        return ToolResult(result.success, result.message, result.data)

    @tool(
        registry,
        name="press_hotkey",
        description="Press a keyboard shortcut containing two to four keys.",
        parameters={"type": "object", "properties": {"keys": {"type": "array"}}, "required": ["keys"]},
        risk=ToolRisk.CONFIRM,
    )
    def press_hotkey(keys: list[str]) -> ToolResult:
        result = desktop.hotkey(keys)
        return ToolResult(result.success, result.message, result.data)

    @tool(
        registry,
        name="scroll_screen",
        description="Scroll the currently focused window. Positive values scroll up and negative values scroll down.",
        parameters={"type": "object", "properties": {"amount": {"type": "integer", "minimum": -100, "maximum": 100}}, "required": ["amount"]},
        risk=ToolRisk.CONFIRM,
    )
    def scroll_screen(amount: int) -> ToolResult:
        result = desktop.scroll(amount)
        return ToolResult(result.success, result.message, result.data)
