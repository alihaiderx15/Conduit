"""Desktop observation and structured visual perception."""
from .capture import DesktopCaptureService
from .locator import ScreenElementNotFound, ScreenLocator
from .models import (
    Rectangle,
    ScreenAnalysis,
    ScreenCapture,
    ScreenChange,
    ScreenElement,
    StructuredScreenAnalysis,
    WindowInfo,
)
from .observer import DesktopObserver
from .parser import ScreenAnalysisParseError, parse_structured_screen_analysis
from .verifier import compare_screen_states
from .workflow import LocatedTarget, ObserveActWorkflow, VerifiedDesktopAction

__all__ = [
    "DesktopCaptureService", "DesktopObserver", "Rectangle", "ScreenAnalysis",
    "ScreenCapture", "ScreenChange", "ScreenElement", "StructuredScreenAnalysis",
    "WindowInfo", "ScreenLocator", "ScreenElementNotFound", "ScreenAnalysisParseError",
    "parse_structured_screen_analysis", "compare_screen_states", "LocatedTarget",
    "ObserveActWorkflow", "VerifiedDesktopAction",
]
