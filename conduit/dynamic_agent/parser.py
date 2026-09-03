"""Strict parser for one dynamic-agent decision."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from conduit.memory import MemoryCategory, MemoryProposal

from .models import AgentDecision, AgentDecisionKind




_ACTION_ALIASES = {
    "desktop.launch_app": "system.open_app",
    "system.launch_app": "system.open_app",
    "desktop.open_app": "system.open_app",
    "app.open": "system.open_app",
    "launch_app": "system.open_app",
    "window.activate": "system.activate_window",
    "desktop.activate_window": "system.activate_window",
    "window.focus": "system.activate_window",
    "window.resize": "system.move_resize_window",
    "desktop.move_window": "system.move_resize_window",
    "desktop.set_window_bounds": "system.move_resize_window",
    "window.move_resize": "system.move_resize_window",
    "clipboard.get": "clipboard.read",
    "clipboard.set": "clipboard.write",
    "file.read": "files.read_text",
    "file.list_recent": "files.list_recent",
    "process.check": "system.process_info",
    "web_search": "web.search",
    "search.web": "web.search",
    "search.news": "web.news",
    "deep_research": "web.research",
    "product_search": "web.price_search",
    "price_search": "web.price_search",
    "compare_items": "web.compare",
}


def _normalize_action(
    action: str,
    arguments: dict[str, Any],
    allowed: set[str],
) -> tuple[str, dict[str, Any]]:
    """Map common model-invented names to safe registered Conduit actions."""

    normalized = _ACTION_ALIASES.get(action, action)
    args = dict(arguments)

    # Shell execution is never generally enabled. Convert only a tiny allow-list
    # of explicit application-launch commands to the safer system.open_app tool.
    if action in {"shell.execute", "shell.run", "command.execute"}:
        command = str(
            args.get("command")
            or args.get("cmd")
            or args.get("executable")
            or ""
        ).strip()
        executable = command.split()[0].strip('"').casefold() if command else ""
        safe_apps = {
            "notepad": "notepad",
            "notepad.exe": "notepad",
            "calc": "calculator",
            "calc.exe": "calculator",
            "mspaint": "paint",
            "mspaint.exe": "paint",
            "explorer": "explorer",
            "explorer.exe": "explorer",
        }
        if executable in safe_apps and "system.open_app" in allowed:
            return "system.open_app", {"app": safe_apps[executable]}
        return action, args

    if normalized == "system.open_app":
        app = (
            args.get("app")
            or args.get("application")
            or args.get("name")
            or args.get("executable")
        )
        if app is not None:
            args = {"app": app}

    elif normalized in {"system.activate_window", "system.window_bounds"}:
        if "window_title" in args and "title" not in args:
            args["title"] = args.pop("window_title")
        if "window_handle" in args and "handle" not in args:
            args["handle"] = args.pop("window_handle")
        if "process_name" in args and "title" not in args:
            args["title"] = str(args.pop("process_name")).removesuffix(".exe")
        if "process" in args and "title" not in args:
            args["title"] = str(args.pop("process")).removesuffix(".exe")
        if "name" in args and "title" not in args:
            args["title"] = args.pop("name")

    elif normalized == "system.list_processes":
        process = args.get("process") or args.get("process_name") or args.get("name")
        if process is not None and "system.process_info" in allowed:
            return "system.process_info", {"process": process}
        args = {}

    elif normalized == "desktop.type":
        if "content" in args and "text" not in args:
            args["text"] = args.pop("content")
        if "value" in args and "text" not in args:
            args["text"] = args.pop("value")

    elif normalized == "clipboard.write":
        if "content" in args and "text" not in args:
            args["text"] = args.pop("content")

    return normalized, args


class AgentDecisionError(ValueError):
    """Raised when a provider returns an invalid next-action decision."""


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise AgentDecisionError("The response did not contain a JSON object.")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AgentDecisionError(f"Invalid decision JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentDecisionError("The decision must be a JSON object.")
    return value




def _parse_memory_proposals(raw: object) -> tuple[MemoryProposal, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise AgentDecisionError("memory_proposals must be an array.")
    proposals: list[MemoryProposal] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise AgentDecisionError(f"memory_proposals[{index}] must be an object.")
        key = str(item.get("key", "")).strip()
        value = str(item.get("value", "")).strip()
        if not key or not value:
            raise AgentDecisionError(f"memory_proposals[{index}] requires key and value.")
        try:
            category = MemoryCategory(str(item.get("category", "fact")).strip().lower())
        except ValueError as exc:
            raise AgentDecisionError(f"memory_proposals[{index}] has an invalid category.") from exc
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError) as exc:
            raise AgentDecisionError(f"memory_proposals[{index}] importance must be numeric.") from exc
        if not 0 <= importance <= 1:
            raise AgentDecisionError(f"memory_proposals[{index}] importance must be between 0 and 1.")
        proposals.append(MemoryProposal(
            key=key,
            value=value,
            category=category,
            importance=importance,
            reason=str(item.get("reason", "")).strip(),
        ))
    return tuple(proposals)

def parse_decision(text: str, *, allowed_actions: Iterable[str]) -> AgentDecision:
    """Parse and validate one model decision."""

    raw = _extract_json(text)
    try:
        kind = AgentDecisionKind(str(raw.get("decision", "")).strip().lower())
    except ValueError as exc:
        raise AgentDecisionError("decision must be act, finish, fail, or ask_user.") from exc

    reason = str(raw.get("reason", "")).strip()
    memory_proposals = _parse_memory_proposals(raw.get("memory_proposals"))
    if not reason:
        raise AgentDecisionError("reason is required.")

    if kind is AgentDecisionKind.ACT:
        action = str(raw.get("action", "")).strip()
        allowed = set(allowed_actions)
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            raise AgentDecisionError("arguments must be an object.")
        action, arguments = _normalize_action(action, arguments, allowed)
        if action not in allowed:
            raise AgentDecisionError(
                f"Unsupported action: {action!r}. Use one of the exact AVAILABLE ACTIONS names."
            )
        save_as = raw.get("save_as", {})
        if not isinstance(save_as, dict) or not all(
            isinstance(name, str) and isinstance(path, str) for name, path in save_as.items()
        ):
            raise AgentDecisionError("save_as must be an object mapping variable names to result paths.")
        return AgentDecision(
            kind=kind,
            reason=reason,
            action=action,
            arguments=arguments,
            expected_outcome=str(raw.get("expected_outcome", "")).strip(),
            save_as={name.strip(): path.strip() for name, path in save_as.items()},
            memory_proposals=memory_proposals,
        )

    message = str(raw.get("message", "")).strip()
    if not message:
        raise AgentDecisionError("message is required for finish, fail, and ask_user decisions.")
    return AgentDecision(kind=kind, reason=reason, message=message, memory_proposals=memory_proposals)
