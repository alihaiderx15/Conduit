"""Safe bridge between structured perception and desktop control."""
from __future__ import annotations

from dataclasses import dataclass

from conduit.desktop.controller import DesktopController
from conduit.desktop.models import DesktopActionResult
from conduit.observer.locator import ScreenLocator
from conduit.observer.models import ScreenElement, StructuredScreenAnalysis
from conduit.observer.observer import DesktopObserver
from conduit.observer.verifier import compare_screen_states


@dataclass(frozen=True, slots=True)
class LocatedTarget:
    query: str
    element: ScreenElement
    analysis: StructuredScreenAnalysis


@dataclass(frozen=True, slots=True)
class VerifiedDesktopAction:
    target: ScreenElement
    action: DesktopActionResult
    before: StructuredScreenAnalysis
    after: StructuredScreenAnalysis
    verification_summary: str
    changed: bool


class ObserveActWorkflow:
    """Locate named visual targets and execute explicitly approved actions."""

    def __init__(self, observer: DesktopObserver, controller: DesktopController) -> None:
        self._observer = observer
        self._controller = controller

    async def locate(self, query: str, *, role: str | None = None) -> LocatedTarget:
        analysis = await self._observer.analyze_structured(
            f"Locate visible elements relevant to: {query}"
        )
        element = ScreenLocator(analysis).find(query, role=role)
        return LocatedTarget(query, element, analysis)

    async def click_and_verify(self, located: LocatedTarget, *, approved: bool) -> VerifiedDesktopAction:
        if not approved:
            raise PermissionError("Desktop click was not explicitly approved.")
        x, y = located.element.center
        action = self._controller.click(x, y)
        after = await self._observer.analyze_structured(
            f"Describe the visible state after clicking {located.element.label}."
        )
        change = compare_screen_states(located.analysis, after)
        return VerifiedDesktopAction(
            target=located.element,
            action=action,
            before=located.analysis,
            after=after,
            verification_summary=change.summary,
            changed=change.changed,
        )
