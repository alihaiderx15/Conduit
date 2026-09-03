"""Compare structured screen states after desktop actions."""
from __future__ import annotations

from conduit.observer.models import ScreenChange, StructuredScreenAnalysis


def compare_screen_states(before: StructuredScreenAnalysis, after: StructuredScreenAnalysis) -> ScreenChange:
    before_ids = {element.element_id for element in before.elements if element.visible}
    after_ids = {element.element_id for element in after.elements if element.visible}
    added = tuple(sorted(after_ids - before_ids))
    removed = tuple(sorted(before_ids - after_ids))
    application_changed = before.application.casefold() != after.application.casefold()
    changed = application_changed or bool(added) or bool(removed) or before.summary != after.summary
    if not changed:
        summary = "No meaningful visible change was detected."
    else:
        parts: list[str] = []
        if application_changed:
            parts.append(f"application changed from {before.application} to {after.application}")
        if added:
            parts.append(f"added elements: {', '.join(added)}")
        if removed:
            parts.append(f"removed elements: {', '.join(removed)}")
        summary = "; ".join(parts) or "The visible screen state changed."
    return ScreenChange(changed, application_changed, added, removed, summary)
