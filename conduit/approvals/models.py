"""Task-scoped approval models for controlled autonomous work."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from conduit.planning import PlanStep

_PATH_KEYS = {"path", "source", "destination", "root"}


@dataclass(frozen=True, slots=True)
class ApprovalScope:
    """A narrowly defined set of actions approved for one task."""

    goal: str
    allowed_actions: frozenset[str]
    allowed_path_roots: tuple[Path, ...] = ()
    max_confirmed_actions: int = 20
    expires_after_seconds: int = 300
    argument_constraints: Mapping[str, Mapping[str, tuple[Any, ...]]] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def describe(self) -> str:
        actions = ", ".join(sorted(self.allowed_actions))
        roots = ", ".join(str(path) for path in self.allowed_path_roots) or "no file paths"
        return f"Goal: {self.goal}\nApproved actions: {actions}\nApproved paths: {roots}"


@dataclass(slots=True)
class TaskApprovalSession:
    """Tracks use of one user-approved task scope."""

    scope: ApprovalScope
    approved: bool = False
    used_confirmed_actions: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def approve(self) -> None:
        self.approved = True

    def revoke(self) -> None:
        self.approved = False

    @property
    def expired(self) -> bool:
        return datetime.now(timezone.utc) > self.created_at + timedelta(seconds=self.scope.expires_after_seconds)

    def authorize(self, step: PlanStep) -> tuple[bool, str]:
        if not self.approved:
            return False, "The task scope has not been approved."
        if self.expired:
            return False, "The task approval has expired."
        if step.action not in self.scope.allowed_actions:
            return False, f"Action {step.action!r} is outside the approved task scope."
        if self.used_confirmed_actions >= self.scope.max_confirmed_actions:
            return False, "The approved action limit has been reached."
        if not self._paths_allowed(step.arguments):
            return False, "One or more file paths are outside the approved roots."
        if not self._arguments_allowed(step):
            return False, "One or more action arguments are outside the approved task scope."
        self.used_confirmed_actions += 1
        return True, "Approved by the active task scope."

    def _arguments_allowed(self, step: PlanStep) -> bool:
        constraints = self.scope.argument_constraints.get(step.action, {})
        for key, allowed_values in constraints.items():
            value = step.arguments.get(key)
            normalized = _normalize_constraint_value(key, value)
            normalized_allowed = [_normalize_constraint_value(key, item) for item in allowed_values]
            if normalized not in normalized_allowed:
                return False
        return True

    def _paths_allowed(self, arguments: Mapping[str, Any]) -> bool:
        roots = tuple(path.resolve() for path in self.scope.allowed_path_roots)
        for key, value in arguments.items():
            if key not in _PATH_KEYS or not isinstance(value, str):
                continue
            if not roots:
                return False
            candidate = Path(value).expanduser().resolve()
            if not any(_is_within(candidate, root) for root in roots):
                return False
        return True


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _normalize_constraint_value(key: str, value: Any) -> Any:
    """Normalize equivalent model encodings before scope comparison."""
    if key == "keys":
        if isinstance(value, str):
            parts = [part.strip().casefold() for part in value.replace("+", ",").split(",") if part.strip()]
            return tuple(parts)
        if isinstance(value, (list, tuple)):
            parts: list[str] = []
            for item in value:
                parts.extend(
                    part.strip().casefold()
                    for part in str(item).replace("+", ",").split(",")
                    if part.strip()
                )
            return tuple(parts)
    if isinstance(value, list):
        return tuple(value)
    return value
