"""Windows-visible messaging workflow primitives.

This layer deliberately uses the user's real desktop app/profile or Windows
default browser. It never logs in, bypasses authentication, or uses Conduit's
hidden Playwright profile for private messaging.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path

from conduit.core.models import ToolCall
from conduit.system_control.windows import launch_detached_process

SERVICE_CONFIG = {
    "whatsapp": {
        "processes": ("WhatsApp.exe",),
        "start_app_names": ("WhatsApp",),
        "known_paths": (
            r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe",
        ),
        "window_terms": ("WhatsApp",),
        "web_url": "https://web.whatsapp.com/",
        "search_shortcuts": (("ctrl", "f"),),
    },
    "discord": {
        "processes": ("Discord.exe",),
        "start_app_names": ("Discord",),
        "known_paths": (
            r"%LOCALAPPDATA%\Discord\Update.exe",
        ),
        "window_terms": ("Discord",),
        "web_url": "https://discord.com/channels/@me",
        # Discord's Quick Switcher is opened only after Conduit has first
        # verified/navigated to the Direct Messages (Home) area.
        "search_shortcuts": (("ctrl", "k"),),
    },
    "telegram": {
        "processes": ("Telegram.exe",),
        "start_app_names": ("Telegram", "Telegram Desktop"),
        "known_paths": (
            r"%APPDATA%\Telegram Desktop\Telegram.exe",
            r"%LOCALAPPDATA%\Telegram Desktop\Telegram.exe",
        ),
        "window_terms": ("Telegram",),
        "web_url": "https://web.telegram.org/",
        # Try app-level search shortcuts in order and verify the resulting UI
        # before typing. An unverified shortcut is never trusted.
        "search_shortcuts": (("ctrl", "k"), ("ctrl", "f")),
    },
}


def normalize_service(service: str) -> str:
    value = service.casefold().strip()
    if value not in SERVICE_CONFIG:
        raise ValueError(f"Unsupported messaging service: {service}")
    return value


def _tasklist_names() -> set[str]:
    if sys.platform != "win32":
        return set()
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, check=False,
    )
    names = set()
    import csv
    for row in csv.reader(completed.stdout.splitlines()):
        if row:
            names.add(row[0].casefold())
    return names


def desktop_app_running(service: str) -> bool:
    cfg = SERVICE_CONFIG[normalize_service(service)]
    names = _tasklist_names()
    return any(name.casefold() in names for name in cfg["processes"])


def _registered_start_apps() -> list[dict[str, str]]:
    """Read Windows' registered Start-menu applications, including Store apps."""
    if sys.platform != "win32":
        return []
    command = (
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        raw = completed.stdout.strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "name": str(item.get("Name") or "").strip(),
                "app_id": str(item.get("AppID") or "").strip(),
            }
            for item in data
            if isinstance(item, dict)
        ]
    except Exception:
        return []


def find_installed_client(service: str) -> dict | None:
    """Resolve an installed Win32 or Microsoft Store messaging client."""
    service = normalize_service(service)
    cfg = SERVICE_CONFIG[service]

    # Classic Win32 installs.
    for raw in cfg.get("known_paths", ()):
        path = Path(os.path.expandvars(raw)).expanduser()
        if path.is_file():
            return {
                "kind": "win32",
                "path": str(path),
                "name": path.stem,
            }

    # Microsoft Store / packaged apps are best resolved through Get-StartApps.
    wanted = tuple(name.casefold() for name in cfg.get("start_app_names", ()))
    candidates = []
    for app in _registered_start_apps():
        name = app["name"].casefold()
        if any(token == name or token in name for token in wanted):
            candidates.append(app)
    if candidates:
        # Prefer an exact display-name match, then the shortest matching name.
        candidates.sort(
            key=lambda item: (
                item["name"].casefold() not in wanted,
                len(item["name"]),
            )
        )
        best = candidates[0]
        if best["app_id"]:
            return {
                "kind": "start_app",
                "app_id": best["app_id"],
                "name": best["name"],
            }
    return None


def launch_installed_client(service: str, installed: dict) -> bool:
    """Launch a previously resolved Windows messaging application."""
    if sys.platform != "win32":
        return False
    try:
        if installed.get("kind") == "win32":
            command = [str(installed["path"])]
            if normalize_service(service) == "discord" and Path(str(installed["path"])).name.casefold() == "update.exe":
                command += ["--processStart", "Discord.exe"]
            launch_detached_process(command)
            return True
        if installed.get("kind") == "start_app":
            # explorer shell:AppsFolder is the supported Windows shell route for
            # AUMID/Store apps and does not require knowing their package path.
            launch_detached_process(
                ["explorer.exe", f"shell:AppsFolder\\{installed['app_id']}"]
            )
            return True
    except Exception:
        return False
    return False


async def _activate_service_window(agent, service: str, *, attempts: int = 6) -> dict | None:
    cfg = SERVICE_CONFIG[normalize_service(service)]
    for _ in range(max(1, attempts)):
        for term in cfg["window_terms"]:
            result = await agent.tools.execute(
                ToolCall("system.activate_window", {"title": term}),
                confirmed=True,
            )
            if getattr(result, "success", False):
                return {
                    "service": service,
                    "mode": "desktop",
                    "window_title": str(result.data.get("title", term)),
                    "window_handle": int(result.data.get("handle", 0) or 0),
                    "web_url": "",
                }
        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 0.8}),
            confirmed=True,
        )
    return None


async def ensure_visible_client(agent, service: str) -> dict:
    """Prefer the user's installed desktop client; only then use web fallback."""
    service = normalize_service(service)
    cfg = SERVICE_CONFIG[service]

    # Running app: activate it.
    if desktop_app_running(service):
        activated = await _activate_service_window(agent, service, attempts=3)
        if activated:
            activated["installed_detection"] = "running_process"
            return activated

    # Installed-but-not-running app: resolve through Windows registration or a
    # known Win32 install path and launch it. Do not jump straight to web.
    installed = await __import__("asyncio").to_thread(find_installed_client, service)
    if installed is not None:
        launched = await __import__("asyncio").to_thread(
            launch_installed_client, service, installed
        )
        if launched:
            activated = await _activate_service_window(agent, service, attempts=8)
            if activated:
                activated["installed_detection"] = installed.get("kind", "installed")
                activated["installed_name"] = installed.get("name", "")
                return activated

    # No usable desktop client was found. This is a visible user task, so the
    # fallback must use Windows' configured default browser.
    opened = await agent.tools.execute(
        ToolCall("system.open_url", {"url": cfg["web_url"]}),
        confirmed=True,
    )
    if not getattr(opened, "success", False):
        raise RuntimeError(f"Unable to open {service}.")
    await agent.tools.execute(
        ToolCall("system.wait", {"seconds": 4.0}),
        confirmed=True,
    )
    return {
        "service": service,
        "mode": "web",
        "window_title": "",
        "web_url": cfg["web_url"],
        "browser_policy": "windows_default",
        "installed_detection": "not_found",
    }


async def observe_messaging_description(agent, prompt: str):
    """Run free-form messaging vision with one provider-recovery retry."""
    from conduit.core.errors import ProviderError
    for attempt in range(2):
        observer = getattr(agent.router, "observer", None)
        if observer is None:
            raise RuntimeError(
                "This messaging step needs desktop vision, but the active provider/model "
                "does not currently support vision."
            )
        try:
            return await observer.analyze(prompt)
        except ProviderError as exc:
            if attempt == 0 and hasattr(agent, "recover_provider_error"):
                if await agent.recover_provider_error(exc):
                    continue
            raise


async def classify_client_state(agent, service: str) -> tuple[str, str]:
    """Classify the currently visible messaging client state.

    States:
      ready      - logged in and normal chat/search UI is visibly usable
      logged_out - explicit login/setup/QR/phone-number UI is visible
      loading    - splash, spinner, skeleton, syncing, connecting, blank-but-loading UI
      error      - explicit application/network/error state is visible
      unknown    - cannot prove any of the above

    A loading/unknown state is NOT treated as logged out or as failure by itself.
    """
    observer = getattr(agent.router, "observer", None)
    if observer is None:
        raise RuntimeError(
            "Messaging readiness verification needs desktop vision, but the active "
            "provider/model does not currently support vision."
        )

    analysis = await observe_messaging_description(
        agent,
        f"""Inspect the currently visible {service} messaging client only.
Classify its CURRENT UI state.

Return EXACTLY one first line from:
READY
LOGGED_OUT
LOADING
ERROR
UNKNOWN

Then on a second line give one short reason based only on visible evidence.

READY = a normal usable chats/contact interface is visibly loaded, including a
chat list/search control/message interface or equivalent logged-in messaging UI.
For Discord specifically, READY includes the normal logged-in Discord shell when
its server/DM sidebar, channel/chat content, user panel, or other ordinary client
controls are visibly rendered. Do NOT require a particular DM, Home page, or chat
to be open. If the normal Discord UI is visibly interactive, classify READY.
LOGGED_OUT = QR code, phone-number login, sign-in, link-device, authentication,
welcome/setup screen, or equivalent login flow is visibly present.
LOADING = splash screen, spinner, syncing/loading indicator, skeleton placeholders,
"connecting", blank application content that is visibly still starting, or a
partially loaded messaging UI.
ERROR = explicit application/network/startup error is visible.
UNKNOWN = none of these states can be proven.

Never call a loading/blank/partial screen LOGGED_OUT. Never infer hidden state."""
    )
    raw = analysis.description.strip()
    first = raw.splitlines()[0].strip().casefold() if raw else ""
    mapping = {
        "ready": "ready",
        "logged_out": "logged_out",
        "loading": "loading",
        "error": "error",
        "unknown": "unknown",
    }
    return mapping.get(first, "unknown"), raw


async def classify_whatsapp_ready_compact(agent) -> tuple[str, str]:
    """Fast current-screen WhatsApp readiness probe.

    WhatsApp can already be fully loaded while a broad vision classifier remains
    uncertain. Keep this probe intentionally tiny so each readiness pass answers
    only whether the CURRENT WhatsApp UI is usable, logged out, still loading, or
    visibly broken.
    """
    analysis = await observe_messaging_description(
        agent,
        """Inspect ONLY the currently visible WhatsApp window RIGHT NOW.

Return EXACTLY one first line from:
READY
LOGGED_OUT
NOT_READY
ERROR

READY if the normal logged-in WhatsApp interface is visibly usable, such as ANY
of: chat list, contact/search controls, conversation area, message composer,
sidebar/navigation, or normal WhatsApp desktop controls.
LOGGED_OUT only if a QR/link-device/phone/login/setup screen is visibly present.
NOT_READY only for splash/logo-only, spinner, blank startup content, skeletons,
syncing/connecting, or visibly partial loading UI.
ERROR only for an explicit visible WhatsApp application/network/startup error.

On the second line give one very short visible reason. Judge only the CURRENT
screenshot; do not keep an earlier loading judgement.""",
    )
    raw = analysis.description.strip()
    first = raw.splitlines()[0].strip().casefold() if raw else ""
    mapping = {
        "ready": "ready",
        "logged_out": "logged_out",
        "not_ready": "loading",
        "error": "error",
    }
    return mapping.get(first, "unknown"), raw


async def classify_discord_ready_compact(agent) -> tuple[str, str]:
    """Fast Discord-specific readiness probe used after a cold-start poll.

    The first generic readiness pass distinguishes splash/login/error states. Once
    Discord has had at least one poll to start rendering, this narrower probe avoids
    small vision models getting stuck repeating an earlier LOADING judgement.
    """
    analysis = await observe_messaging_description(
        agent,
        """Inspect ONLY the currently visible Discord window. Decide whether Discord's
normal logged-in MAIN UI is usable RIGHT NOW.

Return EXACTLY one first line from:
READY
LOGGED_OUT
NOT_READY
ERROR

READY if ordinary Discord controls/content are visibly rendered, such as ANY of:
server icons/sidebar, Direct Messages/friends list, channel list, chat/message area,
member list, user panel, or normal navigation controls. It does NOT matter which
server/channel/DM is open. If the normal Discord interface is visibly there, return READY.
LOGGED_OUT only for a visible Discord sign-in/login/authentication/QR/setup screen.
NOT_READY only for a splash/logo-only screen, spinner, blank/black startup content,
skeleton/partially-rendered UI, or obvious loading/connecting state.
ERROR only for an explicit visible Discord startup/network/application error.

On the second line give a very short visible reason. Do not carry forward an earlier
loading judgement; classify only the CURRENT screenshot.""",
    )
    raw = analysis.description.strip()
    first = raw.splitlines()[0].strip().casefold() if raw else ""
    mapping = {
        "ready": "ready",
        "logged_out": "logged_out",
        "not_ready": "loading",
        "error": "error",
    }
    return mapping.get(first, "unknown"), raw


async def classify_login_state(agent, service: str) -> tuple[str, str]:
    """Backward-compatible authentication classification."""
    state, reason = await classify_client_state(agent, service)
    if state == "ready":
        return "logged_in", reason
    if state == "logged_out":
        return "logged_out", reason
    return "unknown", reason


async def _messaging_window_evidence(agent, service: str, client: dict) -> dict:
    """Collect deterministic process/window evidence alongside vision."""
    evidence = {
        "process_running": desktop_app_running(service),
        "window_found": False,
        "window_title": "",
        "mode": str(client.get("mode", "")),
    }
    if client.get("mode") == "desktop":
        result = await agent.tools.execute(
            ToolCall("system.list_windows", {}),
            confirmed=True,
        )
        if getattr(result, "success", False):
            terms = tuple(
                x.casefold()
                for x in SERVICE_CONFIG[normalize_service(service)]["window_terms"]
            )
            for item in result.data.get("windows", []):
                title = str(item.get("title", ""))
                if any(term in title.casefold() for term in terms):
                    evidence["window_found"] = True
                    evidence["window_title"] = title
                    break
    else:
        # For web fallback the browser process itself is not service-specific.
        # Presence of the visible page is therefore proven primarily by vision.
        evidence["window_found"] = True
    return evidence


async def wait_until_client_ready(
    agent,
    service: str,
    client: dict,
    *,
    timeout_seconds: float = 90.0,
    poll_seconds: float = 1.0,
) -> tuple[str, str, dict]:
    """Wait adaptively until a messaging client is truly usable.

    The loop combines deterministic process/window evidence with repeated vision
    classification. READY continues immediately. LOGGED_OUT and ERROR stop
    immediately. LOADING/UNKNOWN are retried until timeout rather than being
    mistaken for failure.
    """
    import asyncio
    import time

    service = normalize_service(service)

    # Discord startup remains vision-gated because Electron startup time is
    # unpredictable. A visible/foreground Discord window only proves that the
    # process exists; it does not prove the client UI has finished loading.
    # The generic readiness loop below re-checks vision every poll interval and
    # continues immediately once the normal Discord UI is visibly usable.

    deadline = time.monotonic() + max(5.0, float(timeout_seconds))
    poll = max(0.5, min(float(poll_seconds), 5.0))
    attempts = 0
    last_state = "unknown"
    last_reason = ""
    last_evidence: dict = {}

    events = getattr(agent, "events", None)

    while time.monotonic() < deadline:
        attempts += 1
        evidence = await _messaging_window_evidence(agent, service, client)
        last_evidence = evidence

        # If a desktop app disappeared while waiting, stop rather than staring at
        # whatever unrelated window happens to be in the foreground.
        if client.get("mode") == "desktop":
            if not evidence["process_running"] and not evidence["window_found"]:
                return (
                    "error",
                    f"{service.title()} closed before it became ready.",
                    {**evidence, "attempts": attempts},
                )

        # Re-activate a desktop client if another window stole focus while it was loading.
        if client.get("mode") == "desktop" and evidence["window_found"]:
            title = str(evidence.get("window_title", "")).strip()
            if title:
                await agent.tools.execute(
                    ToolCall("system.activate_window", {"title": title}),
                    confirmed=True,
                )

        # On Discord cold starts, use the broad classifier once to catch splash/login/error.
        # From the second poll onward use a narrower CURRENT-screen probe so small vision
        # models do not get stuck repeating a stale LOADING interpretation after the full
        # Discord shell has already rendered.
        if service == "whatsapp":
            # WhatsApp uses the compact CURRENT-screen probe immediately. This
            # avoids long broad-classifier stalls when the normal chat UI is
            # already visibly loaded. Polling still remains adaptive at 1 second.
            state, reason = await classify_whatsapp_ready_compact(agent)
        elif service == "discord" and attempts >= 2:
            state, reason = await classify_discord_ready_compact(agent)
        else:
            state, reason = await classify_client_state(agent, service)
        last_state, last_reason = state, reason

        if events is not None and hasattr(events, "emit"):
            await events.emit(
                "messaging.client.state",
                source="MessagingService",
                payload={
                    "service": service,
                    "state": state,
                    "attempt": attempts,
                    "mode": client.get("mode", ""),
                    "process_running": evidence.get("process_running", False),
                    "window_found": evidence.get("window_found", False),
                },
            )

        if state == "ready":
            return "ready", reason, {**evidence, "attempts": attempts}
        if state in {"logged_out", "error"}:
            return state, reason, {**evidence, "attempts": attempts}

        # LOADING and UNKNOWN mean "not ready yet", not failure.
        await asyncio.sleep(poll)

    return (
        "timeout",
        last_reason or f"{service.title()} did not become ready before the timeout.",
        {**last_evidence, "attempts": attempts, "last_state": last_state},
    )


async def active_window_identity(agent) -> dict:
    result = await agent.tools.execute(
        ToolCall("system.active_window", {}),
        confirmed=True,
    )
    if not getattr(result, "success", False):
        return {"title": "", "handle": 0}
    return {
        "title": str(result.data.get("title", "")).strip(),
        "handle": int(result.data.get("handle", 0) or 0),
    }


async def active_window_title(agent) -> str:
    """Backward-compatible title helper."""
    return str((await active_window_identity(agent)).get("title", ""))





def _identity_title_matches_service(service: str, identity: dict, client: dict | None = None) -> bool:
    """Return True when the active window title clearly identifies the service.

    This is deliberately separate from HWND matching. Electron apps such as
    Discord may replace their startup HWND after becoming ready while keeping a
    clearly service-owned foreground title.
    """
    service = normalize_service(service)
    title = str(identity.get("title", "")).strip()
    if not title:
        return False
    lowered = title.casefold()
    expected_title = str((client or {}).get("window_title", "")).strip().casefold()
    if expected_title and (expected_title in lowered or lowered in expected_title):
        return True
    return any(term.casefold() in lowered for term in SERVICE_CONFIG[service]["window_terms"])


async def emit_messaging_stage(agent, service: str, stage: str, detail: str = "") -> None:
    """Emit a concise user-visible diagnostic checkpoint for messaging flows."""
    events = getattr(agent, "events", None)
    if events is not None and hasattr(events, "emit"):
        await events.emit(
            "messaging.stage",
            source="MessagingService",
            payload={"service": normalize_service(service), "stage": stage, "detail": detail},
        )

def _window_belongs_to_service(
    service: str,
    identity: dict,
    client: dict | None = None,
) -> bool:
    """Prefer stable HWND identity; use title only when no handle is known."""
    service = normalize_service(service)
    active_handle = int(identity.get("handle", 0) or 0)
    expected_handle = int((client or {}).get("window_handle", 0) or 0)

    if expected_handle:
        return active_handle == expected_handle

    return _identity_title_matches_service(service, identity, client)


def _title_belongs_to_service(service: str, title: str, client: dict | None = None) -> bool:
    """Compatibility wrapper for older tests/callers."""
    return _window_belongs_to_service(
        service,
        {"title": title, "handle": 0},
        client,
    )


async def ensure_service_foreground(
    agent,
    service: str,
    client: dict | None = None,
    *,
    attempts: int = 3,
) -> str:
    """Ensure the same messaging window owns foreground focus.

    For desktop clients the stable HWND captured when the app is activated is the
    primary identity. Window titles may change while searching/opening chats and
    therefore are not treated as focus loss.
    """
    service = normalize_service(service)
    tries = max(1, min(int(attempts), 5))
    events = getattr(agent, "events", None)
    expected_handle = int((client or {}).get("window_handle", 0) or 0)

    queries: list[dict] = []
    if expected_handle:
        queries.append({"handle": expected_handle})
    expected_title = str((client or {}).get("window_title", "")).strip()
    if expected_title:
        queries.append({"title": expected_title})
    for term in SERVICE_CONFIG[service]["window_terms"]:
        if not any(q.get("title", "").casefold() == term.casefold() for q in queries):
            queries.append({"title": term})

    for attempt in range(1, tries + 1):
        identity = await active_window_identity(agent)
        if _window_belongs_to_service(service, identity, client):
            return str(identity.get("title", ""))

        # Discord/Electron can replace its startup HWND after the app becomes
        # ready. If the CURRENT foreground title still clearly proves service
        # ownership, learn the new HWND instead of pointlessly trying to refocus
        # an app that is already in front. This never accepts an unrelated title.
        if expected_handle and _identity_title_matches_service(service, identity, client):
            new_handle = int(identity.get("handle", 0) or 0)
            if new_handle:
                if client is not None:
                    client["window_handle"] = new_handle
                    client["window_title"] = str(identity.get("title", "")).strip() or client.get("window_title", "")
                expected_handle = new_handle
                await emit_messaging_stage(
                    agent, service, "focus_verified",
                    "Foreground window verified; refreshed the app window identity.",
                )
                return str(identity.get("title", ""))

        if events is not None and hasattr(events, "emit"):
            await events.emit(
                "messaging.focus.recovery",
                source="MessagingService",
                payload={
                    "service": service,
                    "attempt": attempt,
                    "max_attempts": tries,
                    "active_window": identity.get("title", ""),
                    "active_handle": identity.get("handle", 0),
                    "expected_handle": expected_handle,
                },
            )

        for query in queries:
            activated = await agent.tools.execute(
                ToolCall("system.activate_window", query),
                confirmed=True,
            )
            if not getattr(activated, "success", False):
                continue
            await agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.35}),
                confirmed=True,
            )
            identity = await active_window_identity(agent)
            if _window_belongs_to_service(service, identity, client):
                # If we originally had no handle, learn it now for future checks.
                if client is not None and not int(client.get("window_handle", 0) or 0):
                    client["window_handle"] = int(identity.get("handle", 0) or 0)
                return str(identity.get("title", ""))

        if attempt < tries:
            await agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.45}),
                confirmed=True,
            )

    raise RuntimeError(
        f"I can't safely open or focus {service.title()} after {tries} attempts, "
        "so I stopped before typing or clicking anything else."
    )


async def force_service_keyboard_focus(
    agent,
    service: str,
    client: dict | None = None,
    *,
    attempts: int = 2,
) -> str:
    """Actively give a messaging window keyboard focus and verify ownership.

    A window can be visible/foreground-looking while Windows still routes keyboard
    input elsewhere.  Shortcut-driven workflows (especially Discord Ctrl+K) must
    therefore perform a real activate-window action immediately before sending
    keys instead of treating a matching foreground identity as sufficient proof.
    """
    service = normalize_service(service)
    tries = max(1, min(int(attempts), 4))

    for _ in range(tries):
        queries: list[dict] = []
        handle = int((client or {}).get("window_handle", 0) or 0)
        if handle:
            queries.append({"handle": handle})
        title = str((client or {}).get("window_title", "")).strip()
        if title:
            queries.append({"title": title})
        for term in SERVICE_CONFIG[service]["window_terms"]:
            if not any(q.get("title", "").casefold() == term.casefold() for q in queries):
                queries.append({"title": term})

        for query in queries:
            activated = await agent.tools.execute(
                ToolCall("system.activate_window", query),
                confirmed=True,
            )
            if not getattr(activated, "success", False):
                continue
            await agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.12}),
                confirmed=True,
            )
            identity = await active_window_identity(agent)
            if _window_belongs_to_service(service, identity, client) or _identity_title_matches_service(service, identity, client):
                new_handle = int(identity.get("handle", 0) or 0)
                if client is not None and new_handle:
                    client["window_handle"] = new_handle
                    visible_title = str(identity.get("title", "")).strip()
                    if visible_title:
                        client["window_title"] = visible_title
                return str(identity.get("title", ""))

        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 0.15}),
            confirmed=True,
        )

    raise RuntimeError(
        f"I couldn't give {service.title()} keyboard focus, so I stopped before sending a shortcut or typing."
    )


async def observe_service_screen(agent, service: str, client: dict, goal: str):
    """Observe only after proving the intended messaging client is foreground."""
    await ensure_service_foreground(agent, service, client)
    analysis = await observe_messaging_screen(agent, goal)
    # The foreground can change while vision is running. Re-prove it before any
    # returned coordinates are trusted.
    await ensure_service_foreground(agent, service, client)
    return analysis


async def click_service_element(
    agent,
    service: str,
    client: dict,
    element,
    *,
    attempts: int = 3,
) -> None:
    """Click a messenger UI element with focus recovery and verification.

    A successful reactivation alone is not enough: if the intended click caused
    focus loss, Conduit re-focuses the messenger and retries that SAME click.
    It only returns after a click leaves the messenger in the foreground.
    """
    service = normalize_service(service)
    tries = max(1, min(int(attempts), 5))

    for attempt in range(1, tries + 1):
        await ensure_service_foreground(agent, service, client, attempts=3)
        await click_element(agent, element)

        identity = await active_window_identity(agent)
        if _window_belongs_to_service(service, identity, client):
            return

        # The click itself escaped/minimized/switched away from the messenger.
        # Recover focus, then retry the intended click instead of typing blindly.
        if attempt < tries:
            await ensure_service_foreground(agent, service, client, attempts=3)
            await agent.tools.execute(
                ToolCall("system.wait", {"seconds": 0.3}),
                confirmed=True,
            )

    raise RuntimeError(
        f"I can't safely keep {service.title()} focused while using the requested "
        f"control after {tries} attempts, so I stopped before typing anything."
    )


async def type_service_text(agent, service: str, client: dict, text: str) -> None:
    # Prove ownership immediately before typing. Do not force-reactivate after
    # typing: the next vision/action step will verify the stable window handle.
    await ensure_service_foreground(agent, service, client)
    await type_text(agent, text)


async def service_hotkey(agent, service: str, client: dict, keys) -> None:
    # Same rule for shortcuts: verify before sending keys, then verify resulting
    # UI semantically instead of repeatedly forcing foreground activation.
    await ensure_service_foreground(agent, service, client)
    await hotkey(agent, keys)


async def reset_contact_search_state(agent, service: str, client: dict) -> None:
    """Return the messenger to a neutral state before starting a new contact search.

    Previous failed searches or open chats can leave focus inside a result list or
    an in-chat search. Escape is safe only after foreground ownership is proven.
    We use a small bounded reset, then verify the messenger is still foreground.
    """
    service = normalize_service(service)
    await ensure_service_foreground(agent, service, client, attempts=3)

    # Two Esc presses are enough to dismiss a stale search/results overlay and
    # return from a nested/in-chat search on supported messaging clients.
    for _ in range(2):
        await service_press(agent, service, client, "esc")
        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 0.15}),
            confirmed=True,
        )

    await ensure_service_foreground(agent, service, client, attempts=3)


async def compact_messaging_check(
    agent,
    service: str,
    client: dict,
    prompt: str,
    *,
    allowed_tokens: tuple[str, ...],
) -> tuple[str, str]:
    """Run a tiny free-form vision classification instead of structured JSON."""
    await ensure_service_foreground(agent, service, client, attempts=3)
    analysis = await observe_messaging_description(agent, prompt)
    raw = analysis.description.strip()
    first = raw.splitlines()[0].strip().upper() if raw else ""
    for token in allowed_tokens:
        if first == token.upper():
            return token.upper(), raw
    return "UNKNOWN", raw


async def locate_message_composer_center(
    agent,
    service: str,
    client: dict,
) -> tuple[int, int]:
    """Locate only the message composer center using a tiny parseable response."""
    await ensure_service_foreground(agent, service, client, attempts=3)
    analysis = await observe_messaging_description(
        agent,
        f"""Inspect only the active {service} chat.
Find the TEXT INPUT used to type a new outgoing message.

Return EXACTLY one line:
COMPOSER x y

where x and y are integer PIXEL coordinates for the CENTER of the message input.

If you cannot confidently see the outgoing message input, return exactly:
NO_COMPOSER

Do not return JSON. Do not return markdown. Do not choose the chat search box,
contact search box, browser address bar, or any other input.""",
    )
    raw = analysis.description.strip()
    import re
    match = re.search(r"(?im)^\s*COMPOSER\s+(\d+)\s+(\d+)\s*$", raw)
    if not match:
        raise RuntimeError(
            f"I opened the chat, but I couldn't safely locate the {service.title()} "
            "message box."
        )
    x, y = int(match.group(1)), int(match.group(2))
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    width, height = desktop.screen_bounds()
    if not (0 <= x < width and 0 <= y < height):
        raise RuntimeError(
            f"The detected {service.title()} message-box coordinates were outside "
            "the current screen, so I stopped."
        )
    return x, y


async def click_service_xy(
    agent,
    service: str,
    client: dict,
    x: int,
    y: int,
) -> None:
    """Guard foreground, click a verified point, and re-check ownership."""
    await ensure_service_foreground(agent, service, client, attempts=3)
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    await __import__("asyncio").to_thread(desktop.click, int(x), int(y))
    await ensure_service_foreground(agent, service, client, attempts=3)


async def ensure_discord_direct_messages(agent, client: dict) -> None:
    """Put Discord in its Home/Direct Messages area before recipient search.

    Discord's Ctrl+K Quick Switcher works globally, but Conduit's user-facing
    workflow intentionally enters Direct Messages first. Vision verifies the
    current state and, when needed, locates the Home/Direct Messages control.
    """
    service = "discord"
    await emit_messaging_stage(agent, service, "dm_area", "Checking Discord Direct Messages/Home area.")
    await ensure_service_foreground(agent, service, client, attempts=3)

    state, _ = await compact_messaging_check(
        agent,
        service,
        client,
        """Inspect only the active Discord client.
Return EXACTLY one first line:
DM_HOME_READY
or
DISCORD_LOGGED_OUT
or
DM_HOME_NOT_READY

DM_HOME_READY only if Discord's Home/Direct Messages area is visibly active and
usable (for example the Friends/Direct Messages view or DM list is visible).
DISCORD_LOGGED_OUT only if a Discord sign-in/login/authentication screen, QR/login
flow, or equivalent logged-out UI is visibly present.
A server text/voice channel by itself is DM_HOME_NOT_READY. No JSON.""",
        allowed_tokens=("DM_HOME_READY", "DISCORD_LOGGED_OUT", "DM_HOME_NOT_READY"),
    )
    if state == "DISCORD_LOGGED_OUT":
        raise RuntimeError(
            "Discord isn't logged in. I left Discord open for you; log in first, then ask me to continue."
        )
    if state == "DM_HOME_READY":
        await emit_messaging_stage(agent, service, "dm_area_ready", "Discord Direct Messages/Home area is ready.")
        return

    analysis = await observe_service_screen(
        agent,
        service,
        client,
        """Locate Discord's Home / Direct Messages navigation control that returns
from a server/channel to the user's Direct Messages/Friends area. Return it as a
structured clickable element. Do not choose a server, channel, chat message,
composer, or browser control.""",
    )
    candidates = []
    for element in analysis.interactive_elements():
        text = f"{element.label} {element.text}".casefold()
        if any(term in text for term in ("direct messages", "direct message", "home", "friends")):
            candidates.append(element)
    if not candidates:
        raise RuntimeError(
            "I opened Discord, but I couldn't safely locate its Direct Messages/Home control, "
            "so I stopped before searching for a person."
        )

    # Prefer an explicit Direct Messages/Home label over the broader Friends label.
    candidates.sort(key=lambda e: (
        "direct message" not in f"{e.label} {e.text}".casefold()
        and "home" not in f"{e.label} {e.text}".casefold(),
        -float(getattr(e, "confidence", 0.0)),
    ))
    await emit_messaging_stage(agent, service, "dm_navigation", "Opening Discord Direct Messages/Home.")
    await click_service_element(agent, service, client, candidates[0], attempts=3)
    await agent.tools.execute(ToolCall("system.wait", {"seconds": 0.6}), confirmed=True)

    state, _ = await compact_messaging_check(
        agent,
        service,
        client,
        """Inspect only the active Discord client after navigation.
Return EXACTLY one first line:
DM_HOME_READY
or
DISCORD_LOGGED_OUT
or
DM_HOME_NOT_READY

DM_HOME_READY only if Discord's Home/Direct Messages area is visibly active and
usable. DISCORD_LOGGED_OUT only if a Discord login/authentication screen is
visibly present. No JSON.""",
        allowed_tokens=("DM_HOME_READY", "DISCORD_LOGGED_OUT", "DM_HOME_NOT_READY"),
    )
    if state == "DISCORD_LOGGED_OUT":
        raise RuntimeError(
            "Discord isn't logged in. I left Discord open for you; log in first, then ask me to continue."
        )
    if state != "DM_HOME_READY":
        raise RuntimeError(
            "I tried to open Discord Direct Messages, but I couldn't verify that the DM area "
            "actually opened, so I stopped before typing a name."
        )

    await emit_messaging_stage(agent, service, "dm_area_ready", "Discord Direct Messages/Home area is ready.")


async def open_matching_discord_recipient(agent, client: dict, requested_recipient: str) -> dict:
    """Resolve a Discord user safely with a single visual identity pass.

    Discord's Quick Switcher may expose users outside the caller's friend list.
    Conduit therefore never treats a display-name-only match as sufficient proof
    of identity. Vision is used only to READ the visible filtered user rows;
    Python makes the final deterministic identity decision. Selection itself is
    keyboard-only, so no screenshot coordinates are trusted.

    A recipient is safe to open automatically when the requested text exactly
    matches a visible Discord username (case-insensitive, optional leading @).
    If only a display name matches, Conduit stops and surfaces the visible
    username(s) so the user can explicitly disambiguate on the next turn.
    """
    import re

    service = "discord"
    await ensure_service_foreground(agent, service, client, attempts=1)
    analysis = await observe_messaging_description(
        agent,
        f"""Inspect only Discord's currently open Quick Switcher after Conduit
searched for @{requested_recipient}.

Read the selectable USER result rows currently visible. Do not decide which
account Conduit should open. Do not infer friendship or identity.

Return one line per visible user row, from top to bottom, exactly as:
USER | <display name> | <username>

Use the visible Discord username without a leading @. If a field is not visible,
leave that field empty. Return at most 10 rows. If there are no user rows, return
exactly:
NO_USERS

Do not return coordinates, JSON, markdown, explanations, or any other text.""",
    )
    await ensure_service_foreground(agent, service, client, attempts=1)

    rows: list[dict[str, str | int]] = []
    for raw_line in analysis.description.splitlines():
        line = raw_line.strip()
        if not line.upper().startswith("USER |"):
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) != 3:
            continue
        display_name = parts[1][:120]
        username = parts[2].lstrip("@").strip()[:120]
        if not display_name and not username:
            continue
        rows.append({
            "index": len(rows) + 1,
            "display_name": display_name,
            "username": username,
        })
        if len(rows) >= 10:
            break

    if not rows:
        raise RuntimeError(
            f"I couldn't see a Discord user result matching {requested_recipient}."
        )

    def norm(value: str) -> str:
        value = value.strip().lstrip("@").casefold()
        return re.sub(r"\s+", " ", value)

    requested_norm = norm(requested_recipient)
    exact_username = [row for row in rows if norm(str(row["username"])) == requested_norm]

    if len(exact_username) == 1:
        chosen = exact_username[0]
    elif len(exact_username) > 1:
        # Discord usernames are unique, but fail closed if vision duplicated rows.
        raise RuntimeError(
            f"Discord showed more than one result for the exact username @{requested_recipient}, "
            "so I stopped instead of guessing."
        )
    else:
        exact_display = [row for row in rows if norm(str(row["display_name"])) == requested_norm]
        if exact_display:
            identities = []
            for row in exact_display[:5]:
                display = str(row["display_name"]).strip() or requested_recipient
                username = str(row["username"]).strip()
                identities.append(f"{display} (@{username})" if username else display)
            shown = ", ".join(identities)
            raise RuntimeError(
                f"I found {shown} in Discord, but {requested_recipient!r} only matches the "
                "display name, not a verified Discord username. I won't guess which account "
                "you mean. Ask me again using the exact @username shown for the right person."
            )
        raise RuntimeError(
            f"I couldn't safely match {requested_recipient} to a visible Discord username. "
            "Try the person's exact Discord @username."
        )

    index = int(chosen["index"])
    await emit_messaging_stage(
        agent, service, "open_matching_result",
        f"Opening DM with @{chosen['username']}.",
    )

    # Discord highlights the first filtered user. Keyboard-only navigation avoids
    # DPI/multi-monitor coordinate errors.
    for _ in range(index - 1):
        await service_press(agent, service, client, "down")
        await agent.tools.execute(ToolCall("system.wait", {"seconds": 0.04}), confirmed=True)
    await service_press(agent, service, client, "enter")
    await agent.tools.execute(ToolCall("system.wait", {"seconds": 0.25}), confirmed=True)

    return {
        "display_name": str(chosen["display_name"]).strip(),
        "username": str(chosen["username"]).strip(),
        "index": index,
    }


async def open_contact_search(agent, service: str, client: dict):
    """Open the messenger's global contact/chat search UI.

    Discord uses a deterministic keyboard fast path. Once Windows proves Discord
    owns keyboard focus, Ctrl+K is trusted to open Discord's Quick Switcher; no
    vision round-trip is spent re-confirming a predictable shortcut result.
    Other messaging services keep the existing verified workflow.
    """
    service = normalize_service(service)

    if service == "discord":
        # Discord can be visible without owning keyboard focus, so actively give
        # it keyboard focus immediately before Ctrl+K. Once focus is proven,
        # trust Discord's native shortcut instead of waiting on vision.
        await force_service_keyboard_focus(agent, service, client, attempts=2)
        await service_hotkey(agent, service, client, ("ctrl", "k"))
        # Discord can take a moment to render the Quick Switcher even after the
        # shortcut is accepted. This is a deterministic UI-settle delay, not a
        # vision confirmation loop.
        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 2.0}),
            confirmed=True,
        )
        return True

    if service == "whatsapp":
        # WhatsApp Ctrl+F is deterministic once the app really owns keyboard
        # focus. Avoid an extra vision round-trip just to confirm the search box;
        # give the UI one second to render before typing the contact.
        await force_service_keyboard_focus(agent, service, client, attempts=2)
        await service_hotkey(agent, service, client, ("ctrl", "f"))
        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 1.0}),
            confirmed=True,
        )
        return True

    await emit_messaging_stage(agent, service, "search_prepare", "Preparing contact search.")
    await reset_contact_search_state(agent, service, client)
    shortcuts = SERVICE_CONFIG[service].get("search_shortcuts", ())
    if not shortcuts:
        raise RuntimeError(
            f"{service.title()} does not have a configured safe contact-search shortcut."
        )

    for shortcut in shortcuts:
        await emit_messaging_stage(agent, service, "search_open", "Opening contact search.")
        await ensure_service_foreground(agent, service, client, attempts=3)
        await service_hotkey(agent, service, client, shortcut)
        await agent.tools.execute(
            ToolCall("system.wait", {"seconds": 0.35}),
            confirmed=True,
        )
        state, _ = await compact_messaging_check(
            agent,
            service,
            client,
            f"""Inspect only the active {service} window after Conduit used the configured
contact-search shortcut.

Return EXACTLY one first line:
SEARCH_READY
or
NOT_READY

SEARCH_READY only if the global contact/chat search UI is visibly open and ready
for a contact name. Do not return JSON.""",
            allowed_tokens=("SEARCH_READY", "NOT_READY"),
        )
        if state == "SEARCH_READY":
            return True

    raise RuntimeError(
        f"I couldn't verify that {service.title()}'s contact search opened, so I stopped before typing a name."
    )


async def service_press(agent, service: str, client: dict, key: str) -> None:
    await ensure_service_foreground(agent, service, client)
    await press(agent, key)


async def observe_messaging_screen(agent, goal: str):
    from conduit.core.errors import ProviderError
    for attempt in range(2):
        observer = getattr(agent.router, "observer", None)
        if observer is None:
            raise RuntimeError(
                "This messaging step needs desktop vision, but the active provider/model "
                "does not currently support vision."
            )
        try:
            return await observer.analyze_structured(goal)
        except ProviderError as exc:
            if attempt == 0 and hasattr(agent, "recover_provider_error"):
                recovered = await agent.recover_provider_error(exc)
                if recovered:
                    continue
            raise


async def click_element(agent, element) -> None:
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    await __import__("asyncio").to_thread(desktop.click, *element.center)


async def type_text(agent, text: str) -> None:
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    await __import__("asyncio").to_thread(desktop.type_text, text)


async def press(agent, key: str) -> None:
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    await __import__("asyncio").to_thread(desktop.press_key, key)


async def hotkey(agent, keys) -> None:
    desktop = getattr(agent.router, "desktop", None)
    if desktop is None:
        raise RuntimeError("Desktop control is not enabled.")
    await __import__("asyncio").to_thread(desktop.hotkey, keys)
