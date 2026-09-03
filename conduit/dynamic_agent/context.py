"""Typed working-memory and variable resolution for dynamic agent runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from .models import AgentObservation

_REFERENCE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}$")
_EMBEDDED_REFERENCE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*\}\}")
_MISSING = object()


class VariableResolutionError(ValueError):
    """Raised when an action references a variable that is not available."""


@dataclass(frozen=True, slots=True)
class ContextVariable:
    """One named value retained in the current agent run."""

    name: str
    value: Any
    source: str
    iteration: int | None = None
    source_path: str | None = None


class VariableStore:
    """Store typed values and safely resolve references inside action arguments."""

    def __init__(self, initial: Mapping[str, Any] | None = None) -> None:
        self._values: dict[str, ContextVariable] = {}
        for name, value in (initial or {}).items():
            self.set(name, value, source="initial")

    def set(
        self,
        name: str,
        value: Any,
        *,
        source: str,
        iteration: int | None = None,
        source_path: str | None = None,
    ) -> None:
        normalized = self._validate_name(name)
        self._values[normalized] = ContextVariable(
            normalized,
            value,
            source,
            iteration,
            source_path,
        )

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Read a variable, allowing dotted traversal into dictionaries and lists."""
        parts = path.split(".")
        root = self._values.get(parts[0])
        if root is None:
            if default is not _MISSING:
                return default
            raise VariableResolutionError(f"Unknown context variable: {parts[0]!r}.")
        current = root.value
        for part in parts[1:]:
            if isinstance(current, Mapping):
                if part not in current:
                    if default is not _MISSING:
                        return default
                    raise VariableResolutionError(f"Variable path {path!r} does not exist.")
                current = current[part]
            elif isinstance(current, (list, tuple)) and part.isdigit():
                index = int(part)
                try:
                    current = current[index]
                except IndexError as exc:
                    if default is not _MISSING:
                        return default
                    raise VariableResolutionError(f"Variable path {path!r} is out of range.") from exc
            else:
                if default is not _MISSING:
                    return default
                raise VariableResolutionError(f"Variable path {path!r} cannot be traversed.")
        return current

    def resolve(self, value: Any) -> Any:
        """Resolve {{variable.path}} references recursively inside JSON-like values."""
        if isinstance(value, Mapping):
            return {str(key): self.resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.resolve(item) for item in value)
        if not isinstance(value, str):
            return value

        exact = _REFERENCE.fullmatch(value)
        if exact:
            return self.get(exact.group(1))

        def replace(match: re.Match[str]) -> str:
            resolved = self.get(match.group(1))
            return str(resolved)

        return _EMBEDDED_REFERENCE.sub(replace, value)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-friendly plain-value snapshot for prompts and reports."""
        return {name: variable.value for name, variable in self._values.items()}

    def metadata(self) -> dict[str, dict[str, Any]]:
        """Return provenance information for diagnostics and future UI displays."""
        return {
            name: {
                "source": variable.source,
                "iteration": variable.iteration,
                "source_path": variable.source_path,
            }
            for name, variable in self._values.items()
        }

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", normalized):
            raise ValueError(f"Invalid variable name: {name!r}.")
        return normalized


def extract_path(payload: Mapping[str, Any], path: str) -> Any:
    """Extract a dotted path from an observation payload."""
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, (list, tuple)) and part.isdigit():
            try:
                current = current[int(part)]
            except IndexError as exc:
                raise VariableResolutionError(f"Capture path {path!r} is out of range.") from exc
        else:
            raise VariableResolutionError(f"Capture path {path!r} was not present in the action result.")
    return current


class AgentContext:
    """Mutable run context containing observations and reusable typed variables."""

    def __init__(self, goal: str, initial_variables: Mapping[str, Any] | None = None) -> None:
        self.goal = goal
        self.observations: list[AgentObservation] = []
        self.store = VariableStore(initial_variables)

    @property
    def variables(self) -> dict[str, Any]:
        """Backwards-compatible plain variable snapshot."""
        return self.store.snapshot()

    def resolve_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        resolved = self.store.resolve(dict(arguments))
        assert isinstance(resolved, dict)
        return resolved

    def add_observation(
        self,
        observation: AgentObservation,
        *,
        captures: Mapping[str, str] | None = None,
    ) -> None:
        self.observations.append(observation)
        record = {
            "action": observation.action,
            "arguments": dict(observation.arguments),
            "success": observation.success,
            "message": observation.message,
            "data": dict(observation.data),
            "error_type": observation.error_type,
        }
        step_name = f"step_{observation.iteration}"
        self.store.set(step_name, record, source="observation", iteration=observation.iteration)
        self.store.set("last", record, source="observation", iteration=observation.iteration)
        self.store.set(
            "last_success" if observation.success else "last_failure",
            record,
            source="observation",
            iteration=observation.iteration,
        )

        capture_warnings: list[dict[str, str]] = []
        for name, path in (captures or {}).items():
            try:
                value = extract_path(record, path)
            except VariableResolutionError as exc:
                # A model may request an optional or provider-specific result field.
                # Preserve the successful action observation and let the agent recover
                # on the next iteration instead of crashing the entire run.
                capture_warnings.append({
                    "name": name,
                    "path": path,
                    "error": str(exc),
                })
                continue
            self.store.set(
                name,
                value,
                source="capture",
                iteration=observation.iteration,
                source_path=path,
            )

        if capture_warnings:
            self.store.set(
                "last_capture_warnings",
                capture_warnings,
                source="capture_warning",
                iteration=observation.iteration,
            )
