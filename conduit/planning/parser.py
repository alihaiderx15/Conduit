"""Parse and validate provider-generated task plans."""
from __future__ import annotations
import json
import re
from typing import Any, Iterable
from .errors import PlanParseError, PlanValidationError
from .models import PlanStep, StepCapability, TaskPlan


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.I | re.S)
    candidate = fenced.group(1) if fenced else stripped
    if not candidate.startswith("{"):
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start:end + 1]
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PlanParseError(f"Planner did not return valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PlanParseError("Planner response must be a JSON object.")
    return value


def parse_plan(text: str, *, allowed_actions: Iterable[str], max_steps: int = 20) -> TaskPlan:
    payload = _extract_json(text)
    try:
        goal = str(payload["goal"]).strip()
        summary = str(payload.get("summary", "")).strip()
        raw_steps = payload["steps"]
    except KeyError as exc:
        raise PlanParseError(f"Missing required plan field: {exc.args[0]}") from exc
    if not goal:
        raise PlanValidationError("Plan goal cannot be empty.")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PlanValidationError("Plan must contain at least one step.")
    if len(raw_steps) > max_steps:
        raise PlanValidationError(f"Plan exceeds the maximum of {max_steps} steps.")

    allowed = set(allowed_actions)
    steps: list[PlanStep] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise PlanValidationError(f"Step {index} must be an object.")
        step_id = str(raw.get("id", f"step_{index}")).strip()
        if not step_id or step_id in seen:
            raise PlanValidationError(f"Step IDs must be non-empty and unique: {step_id!r}")
        action = str(raw.get("action", "")).strip()
        if action not in allowed:
            raise PlanValidationError(f"Step '{step_id}' uses unavailable action '{action}'.")
        try:
            capability = StepCapability(str(raw.get("capability", "")))
        except ValueError as exc:
            raise PlanValidationError(f"Step '{step_id}' has invalid capability.") from exc
        dependencies = tuple(str(x) for x in raw.get("depends_on", []) or [])
        unknown = [item for item in dependencies if item not in seen]
        if unknown:
            raise PlanValidationError(
                f"Step '{step_id}' depends on unknown or later steps: {unknown}."
            )
        arguments = raw.get("arguments", {}) or {}
        if not isinstance(arguments, dict):
            raise PlanValidationError(f"Step '{step_id}' arguments must be an object.")
        steps.append(PlanStep(
            id=step_id,
            title=str(raw.get("title", action)).strip() or action,
            capability=capability,
            action=action,
            arguments=arguments,
            depends_on=dependencies,
            requires_confirmation=bool(raw.get("requires_confirmation", False)),
            success_criteria=str(raw.get("success_criteria", "")).strip(),
        ))
        seen.add(step_id)

    assumptions_raw = payload.get("assumptions", []) or []
    if not isinstance(assumptions_raw, list):
        raise PlanValidationError("Plan assumptions must be an array.")
    return TaskPlan(
        goal=goal,
        summary=summary,
        steps=tuple(steps),
        assumptions=tuple(str(x) for x in assumptions_raw),
    )
