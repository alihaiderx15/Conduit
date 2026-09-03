
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from conduit.core.models import ChatMessage, Role


@dataclass(frozen=True, slots=True)
class SystemPlan:
    action: str
    arguments: dict[str, Any]


_ALLOWED = {
    "system.volume_get", "system.volume_set", "system.volume_up",
    "system.volume_down", "system.mute",
    "system.brightness_get", "system.brightness_set",
    "system.brightness_up", "system.brightness_down",
    "system.wifi_status", "system.wifi_toggle",
    "system.dark_mode_get", "system.dark_mode",
    "system.lock", "system.sleep_display",
    "system.open_settings", "system.open_task_manager",
    "system.show_desktop", "system.snap_window", "system.switch_windows",
    "system.browser_zoom", "system.browser_tab_shortcut",
    "system.page_navigation",
    "system.apps_installed", "system.app_status",
    "system.open_app", "system.open_apps",
    "system.close_app", "system.close_apps",
}


class AISystemRouter:
    """Map flexible wording to existing verified system.* actions only."""

    def __init__(self, provider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(self, user_message: str, *, recent_context: str = "") -> SystemPlan | None:
        context = (
            "\nRECENT CONTEXT (use only for clear references like 'turn it back on'):\n"
            + recent_context
            if recent_context.strip()
            else ""
        )
        prompt = f"""You are Conduit's SYSTEM ACTION ROUTER.
Map the CURRENT request to exactly ONE structured system action.
Correct typos, slang, politeness, filler, and unusual word order mentally.
Do not answer the user. Do not invent hotkeys, shell commands, or other tools.
If the request is not clearly a supported Windows/system/app action, return null.

AVAILABLE ACTIONS:
system.volume_get {{}}
system.volume_set {{"value":0-100}}
system.volume_up {{"step":1-100}} default 10
system.volume_down {{"step":1-100}} default 10
system.mute {{"muted":true|false}}
system.brightness_get {{}}
system.brightness_set {{"value":0-100}}
system.brightness_up {{"step":1-100}} default 10
system.brightness_down {{"step":1-100}} default 10
system.wifi_status {{}}
system.wifi_toggle {{"enabled":true|false}}; omit enabled only for explicit toggle
system.dark_mode_get {{}}
system.dark_mode {{"enabled":true|false}}
system.lock {{}}
system.sleep_display {{}}
system.open_settings {{"page":optional string}}
system.open_task_manager {{}}
system.show_desktop {{}}
system.snap_window {{"direction":"left"|"right"}}
system.switch_windows {{}}
system.browser_zoom {{"action":"in"|"out"|"reset"}}
system.browser_tab_shortcut {{"action":"next"|"previous"|"new"|"close"|"reopen"}}
system.page_navigation {{"action":"back"|"forward"|"reload"}}
system.apps_installed {{}}
system.app_status {{"app":string}}
system.open_app {{"app":string}}
system.open_apps {{"apps":[string,...]}}
system.close_app {{"app":string}}
system.close_apps {{"apps":[string,...]}}

INTERPRETATION EXAMPLES:
"enable my wireless" -> system.wifi_toggle {{"enabled":true}}
"get wifi working again" -> system.wifi_toggle {{"enabled":true}}
"disable wireless" -> system.wifi_toggle {{"enabled":false}}
"make it louder" -> system.volume_up {{"step":10}}
"dim my screen a little" -> system.brightness_down {{"step":10}}
"make the screen brighter" -> system.brightness_up {{"step":10}}
"use dark theme" -> system.dark_mode {{"enabled":true}}
"go back to light mode" -> system.dark_mode {{"enabled":false}}
"bring up task manager" -> system.open_task_manager {{}}
"put this window on the left half" -> system.snap_window {{"direction":"left"}}
"open discord and spotify" -> system.open_apps {{"apps":["discord","spotify"]}}
"quit steam and discord" -> system.close_apps {{"apps":["steam","discord"]}}

RULES:
- Prefer the dedicated system.* action.
- Preserve user-supplied app names.
- Never invent an app.
- Use step=10 when a relative volume/brightness request gives no amount.
- Return null if unclear.
- Restart/shutdown are intentionally excluded here because they keep their
  separate explicit-confirmation path.

Return ONLY JSON or null:
{{"action":"system.wifi_toggle","arguments":{{"enabled":true}}}}
{context}

CURRENT REQUEST:
{user_message}
"""
        response = await self.provider.chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.model,
        )
        raw_text = response.text.strip()
        if raw_text.casefold() in {"", "null", "none"}:
            return None

        raw = _parse(raw_text)
        action = str(raw.get("action", "")).strip()
        if action not in _ALLOWED:
            return None
        arguments = raw.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        return SystemPlan(action, dict(arguments))


def _parse(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        value = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise ValueError("System router returned invalid output.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("System router must return an object or null.")
    return value
