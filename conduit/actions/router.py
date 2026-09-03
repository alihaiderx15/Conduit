"""Route unified actions to browser, desktop, vision, or tool backends."""
from __future__ import annotations
from typing import Any
from conduit.browser import BrowserEngine, BrowserTarget, TargetKind
from conduit.capabilities import YouTubeAgent
from conduit.core.models import ToolCall
from conduit.desktop import DesktopController
from conduit.execution import ToolExecutor
from conduit.observer import DesktopObserver, ScreenLocator
from conduit.planning import PlanStep, StepCapability
from .models import ActionOutcome

class UnifiedActionRouter:
    def __init__(self, *, browser: BrowserEngine, tools: ToolExecutor,
                 desktop: DesktopController | None = None,
                 observer: DesktopObserver | None = None) -> None:
        self.browser = browser
        self.tools = tools
        self.desktop = desktop
        self.observer = observer
        self.youtube = YouTubeAgent(browser)
        self._last_screen_analysis = None

    async def execute(self, step: PlanStep) -> ActionOutcome:
        try:
            return await self._execute(step)
        except Exception as exc:
            return ActionOutcome(False, str(exc), error_type=type(exc).__name__)

    async def _execute(self, step: PlanStep) -> ActionOutcome:
        args = dict(step.arguments)
        action = step.action
        if step.capability is StepCapability.TOOL:
            result = await self.tools.execute(ToolCall(action, args), confirmed=True)
            if not hasattr(result, "success"):
                return ActionOutcome(False, getattr(result, "reason", "Confirmation required."), error_type="PendingConfirmation")
            return ActionOutcome(result.success, result.message, dict(result.data), result.error_type)

        if action == "browser.start":
            result = await self.browser.start(); return ActionOutcome(True, result.message)
        if action == "browser.launch_profile":
            result = await self.browser.launch_profile(
                str(args.get("browser", "")),
                profile=str(args.get("profile", "Default")),
                private=bool(args.get("private", False)),
                url=str(args.get("url", "about:blank")),
            ); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.attach_existing":
            result = await self.browser.attach_existing(
                str(args.get("browser", "")),
                endpoint=str(args.get("endpoint", "")),
            ); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.list_sessions":
            result = await self.browser.list_sessions(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.switch_session":
            result = await self.browser.switch_session(str(args["session_id"])); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.use_default_profile":
            result = await self.browser.use_default_profile(
                browser=str(args.get("browser", "")),
                url=str(args.get("url", "about:blank")),
                private=bool(args.get("private", False)),
            ); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.installed":
            result = await self.browser.installed(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.new_tab":
            result = await self.browser.new_tab(str(args.get("url", "about:blank"))); return ActionOutcome(True, result.message, {"url": result.state.url if result.state else ""})
        if action == "browser.close_tab":
            result = await self.browser.close_tab(args.get("tab")); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.close_all_tabs":
            result = await self.browser.close_all_tabs(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.list_tabs":
            result = await self.browser.list_tabs(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.switch_tab":
            result = await self.browser.switch_tab(args["tab"]); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.back":
            result = await self.browser.back(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.forward":
            result = await self.browser.forward(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.reload":
            result = await self.browser.reload(); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.screenshot":
            result = await self.browser.screenshot(str(args.get("path", ""))); return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.download":
            result = await self.browser.download_active(self._target(args), filename=str(args["filename"]) if args.get("filename") else None)
            return ActionOutcome(True, result.message, dict(result.data))
        if action == "browser.goto":
            result = await self.browser.goto(str(args["url"])); return ActionOutcome(True, result.message, {"url": result.state.url if result.state else ""})
        if action == "browser.read_page":
            state = await self.browser.state(); return ActionOutcome(True, "Read the current page.", {"title": state.title, "url": state.url, "visible_text": state.visible_text})
        if action == "browser.fill":
            result = await self.browser.fill(self._target(args), str(args["text"])); return ActionOutcome(True, result.message)
        if action == "browser.click":
            result = await self.browser.click(self._target(args)); return ActionOutcome(True, result.message, {"url": result.state.url if result.state else ""})
        if action == "browser.press":
            key = str(args["key"])
            result = await self.browser.press(self._target(args), key) if "kind" in args else await self.browser.press_page(key)
            return ActionOutcome(True, result.message)
        if action == "browser.scroll":
            result = await self.browser.scroll(delta_y=int(args.get("delta_y", 700))); return ActionOutcome(True, result.message)
        if action == "youtube.play_latest_upload":
            result = await self.youtube.play_latest_upload(str(args["channel"])); return ActionOutcome(True, f"Opened {result.video_title}.", {"channel": result.channel, "video_title": result.video_title, "video_url": result.video_url, "verified": result.verified})

        if action == "vision.observe":
            observer = self._require_observer()
            analysis = await observer.analyze_structured("Identify important visible controls and information.")
            self._last_screen_analysis = analysis
            return ActionOutcome(True, "Observed the visible desktop.", self._analysis_data(analysis))
        if action == "vision.find":
            observer = self._require_observer()
            analysis = await observer.analyze_structured(f"Locate visible elements relevant to: {args['target']}")
            self._last_screen_analysis = analysis
            element = ScreenLocator(analysis).find(str(args["target"]))
            return ActionOutcome(True, f"Located {element.label}.", {"id": element.id, "label": element.label, "role": element.role, "x": element.center[0], "y": element.center[1], "confidence": element.confidence})
        if action == "desktop.click":
            observer = self._require_observer(); desktop = self._require_desktop()
            analysis = await observer.analyze_structured(f"Locate visible elements relevant to: {args['target']}")
            element = ScreenLocator(analysis).find(str(args["target"]))
            result = desktop.click(*element.center)
            return ActionOutcome(result.success, result.message, {**result.data, "target": element.label})
        if action == "desktop.click_xy":
            result=self._require_desktop().click(int(args["x"]),int(args["y"]),button=str(args.get("button","left")),clicks=int(args.get("clicks",1)))
            return ActionOutcome(result.success,result.message,result.data)
        if action == "desktop.move_mouse":
            result=self._require_desktop().move_mouse(int(args["x"]),int(args["y"]))
            return ActionOutcome(result.success,result.message,result.data)
        if action == "desktop.mouse_position":
            point=self._require_desktop().mouse_position()
            return ActionOutcome(True,"Read the mouse pointer position.",{"x":point.x,"y":point.y})
        if action == "desktop.screen_bounds":
            bounds=self._require_desktop().screen_bounds()
            return ActionOutcome(
                True,
                "Read the virtual desktop bounds.",
                {
                    "width": bounds.width,
                    "height": bounds.height,
                    "left": bounds.left,
                    "top": bounds.top,
                    "right": bounds.right,
                    "bottom": bounds.bottom,
                },
            )
        if action == "desktop.type":
            result = self._require_desktop().type_text(str(args["text"])); return ActionOutcome(result.success, result.message, result.data)
        if action == "desktop.press":
            result = self._require_desktop().press_key(str(args["key"]), int(args.get("presses", 1))); return ActionOutcome(result.success, result.message, result.data)
        if action == "desktop.hotkey":
            keys = _normalize_hotkey_keys(args["keys"])
            result = self._require_desktop().hotkey(keys)
            return ActionOutcome(result.success, result.message, result.data)
        if action == "desktop.scroll":
            result = self._require_desktop().scroll(int(args["amount"])); return ActionOutcome(result.success, result.message, result.data)
        raise ValueError(f"Unsupported unified action: {action}")

    def _require_desktop(self) -> DesktopController:
        if self.desktop is None: raise RuntimeError("Desktop control is not configured.")
        return self.desktop
    def _require_observer(self) -> DesktopObserver:
        if self.observer is None: raise RuntimeError("Desktop vision is not configured for this provider/model.")
        return self.observer
    @staticmethod
    def _target(args: dict[str, Any]) -> BrowserTarget:
        return BrowserTarget(kind=TargetKind(str(args["kind"])), value=str(args["value"]), name=str(args["name"]) if args.get("name") is not None else None, exact=bool(args.get("exact", False)))
    @staticmethod
    def _analysis_data(analysis: Any) -> dict[str, Any]:
        return {"application": analysis.application, "summary": analysis.summary, "elements": [{"id": e.id, "label": e.label, "role": e.role, "x": e.center[0], "y": e.center[1], "confidence": e.confidence} for e in analysis.elements]}


def _normalize_hotkey_keys(value: Any) -> list[str]:
    """Accept model outputs such as ['ctrl', 'a'], 'ctrl+a', or 'ctrl,a'."""
    if isinstance(value, str):
        return [item.strip().casefold() for item in value.replace("+", ",").split(",") if item.strip()]
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            parts.extend(
                part.strip().casefold()
                for part in str(item).replace("+", ",").split(",")
                if part.strip()
            )
        return parts
    raise ValueError("Hotkey keys must be a list or a '+'-separated string.")
