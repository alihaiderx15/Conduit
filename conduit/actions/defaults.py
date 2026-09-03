"""Register non-tool engines in the unified action registry."""
from __future__ import annotations
from conduit.planning import StepCapability
from conduit.tools import ToolRisk
from .models import ActionDescriptor
from .registry import UnifiedActionRegistry


def register_default_actions(registry: UnifiedActionRegistry) -> UnifiedActionRegistry:
    actions = (
        ActionDescriptor("browser.start", StepCapability.BROWSER, "Start Conduit's isolated managed Chromium automation sandbox. Prefer browser.use_default_profile for normal user-visible browsing."),
        ActionDescriptor("browser.launch_profile", StepCapability.BROWSER, "Launch a persistent Conduit-owned profile in the requested browser. If browser is omitted, use the Windows default browser. Supports private mode.", {"browser": "optional string", "profile": "optional string", "private": "optional boolean", "url": "optional string"}),
        ActionDescriptor("browser.attach_existing", StepCapability.BROWSER, "Attach automation to an already-running supported browser debugging endpoint without replacing the user's live profile.", {"browser": "optional string", "endpoint": "optional string"}),
        ActionDescriptor("browser.list_sessions", StepCapability.BROWSER, "List all Conduit browser sessions and identify the active one."),
        ActionDescriptor("browser.switch_session", StepCapability.BROWSER, "Switch to a browser session by session_id.", {"session_id": "string"}),
        ActionDescriptor("browser.use_default_profile", StepCapability.BROWSER, "Open the user's real logged-in browser profile. Use the Windows default browser unless the user explicitly names another browser.", {"browser": "optional string", "url": "optional string", "private": "optional boolean"}),
        ActionDescriptor("browser.installed", StepCapability.BROWSER, "List supported installed browsers and identify the Windows default browser."),
        ActionDescriptor("browser.new_tab", StepCapability.BROWSER, "Open a new tab in the active browser session, optionally at a URL.", {"url": "optional string"}),
        ActionDescriptor("browser.close_tab", StepCapability.BROWSER, "Close the active tab or a specified tab in the active browser session.", {"tab": "optional integer or string"}),
        ActionDescriptor("browser.close_all_tabs", StepCapability.BROWSER, "Close all tabs in the active browser window/session."),
        ActionDescriptor("browser.list_tabs", StepCapability.BROWSER, "List tabs in the active session. Full enumeration requires an automation-attached session."),
        ActionDescriptor("browser.switch_tab", StepCapability.BROWSER, "Switch to a tab by index, title, or URL match.", {"tab": "integer or string"}),
        ActionDescriptor("browser.back", StepCapability.BROWSER, "Navigate the active tab backward."),
        ActionDescriptor("browser.forward", StepCapability.BROWSER, "Navigate the active tab forward."),
        ActionDescriptor("browser.reload", StepCapability.BROWSER, "Reload the active tab."),
        ActionDescriptor("browser.screenshot", StepCapability.BROWSER, "Capture the active browser page/window to a PNG file.", {"path": "optional string"}),
        ActionDescriptor("browser.download", StepCapability.BROWSER, "Download by clicking a semantic element in an automation-attached browser session.", {"kind": "string", "value": "string", "name": "optional string", "filename": "optional string"}),
        ActionDescriptor("browser.goto", StepCapability.BROWSER, "Navigate to a URL.", {"url": "string"}),
        ActionDescriptor("browser.read_page", StepCapability.BROWSER, "Read the current page title, URL, and visible text."),
        ActionDescriptor("browser.click", StepCapability.BROWSER, "Click a browser element semantically.", {"kind": "string", "value": "string", "name": "optional string"}),
        ActionDescriptor("browser.fill", StepCapability.BROWSER, "Fill a browser input semantically.", {"kind": "string", "value": "string", "text": "string"}),
        ActionDescriptor("browser.press", StepCapability.BROWSER, "Press a key in the browser.", {"key": "string"}),
        ActionDescriptor("browser.scroll", StepCapability.BROWSER, "Scroll the webpage.", {"delta_y": "integer"}),
        ActionDescriptor("youtube.play_latest_upload", StepCapability.BROWSER, "Play the newest standard YouTube upload from a channel.", {"channel": "string"}),
        ActionDescriptor("youtube.play_latest_matching", StepCapability.BROWSER, "Play the newest relevant YouTube video matching a topic, optionally restricted to an exact channel.", {"query": "string", "channel": "optional string"}),
        ActionDescriptor("vision.observe", StepCapability.VISION, "Capture and structurally analyze the visible desktop."),
        ActionDescriptor("vision.find", StepCapability.VISION, "Locate a visible desktop element by description.", {"target": "string"}),
        ActionDescriptor("desktop.click", StepCapability.DESKTOP, "Locate and click a visible desktop element.", {"target": "string"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.click_xy", StepCapability.DESKTOP, "Click exact screen coordinates when coordinates are already known.", {"x": "integer", "y": "integer", "button": "optional string", "clicks": "optional integer"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.move_mouse", StepCapability.DESKTOP, "Move the mouse pointer to exact known screen coordinates.", {"x": "integer", "y": "integer"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.mouse_position", StepCapability.DESKTOP, "Read the current mouse pointer coordinates."),
        ActionDescriptor("desktop.screen_bounds", StepCapability.DESKTOP, "Read the primary screen dimensions."),
        ActionDescriptor("desktop.type", StepCapability.DESKTOP, "Type text into the focused desktop application.", {"text": "string"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.press", StepCapability.DESKTOP, "Press a keyboard key.", {"key": "string", "presses": "optional integer"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.hotkey", StepCapability.DESKTOP, "Press a keyboard shortcut.", {"keys": "array"}, ToolRisk.CONFIRM),
        ActionDescriptor("desktop.scroll", StepCapability.DESKTOP, "Scroll the focused desktop application.", {"amount": "integer"}, ToolRisk.CONFIRM),
    )
    for action in actions:
        if action.name not in registry:
            registry.register(action)
    return registry
