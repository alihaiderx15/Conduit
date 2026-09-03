from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any


class SystemControlError(RuntimeError):
    pass


def _require_windows() -> None:
    if sys.platform != "win32":
        raise SystemControlError("This system action currently targets Windows.")


def launch_detached_process(command: list[str]) -> subprocess.Popen:
    """Launch a child without inheriting Conduit's console/std handles.

    This is important for Electron launchers/updaters such as Discord: otherwise
    their internal startup logs can appear inside the Conduit conversational shell.
    """
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        flags = 0
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        flags |= int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        kwargs["creationflags"] = flags
    return subprocess.Popen(command, **kwargs)


def _shell_open_detached(target: str) -> None:
    """Shell-open an exe/shortcut/document without attaching it to our console."""
    _require_windows()
    safe = str(target).replace("'", "''")
    # Start-Process resolves .lnk/.url files and normal executables through the
    # Windows shell. PowerShell itself is created without a console and with all
    # standard handles redirected, so descendants cannot dump logs into Conduit.
    script = f"Start-Process -FilePath '{safe}'"
    launch_detached_process([
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-Command",
        script,
    ])


def _ps(script: str, *, timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    _require_windows()
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _normalize_name(value: str) -> str:
    value = re.sub(r"\.(exe|lnk|url)$", "", value.strip(), flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _desktop_shortcuts() -> list[dict[str, str]]:
    _require_windows()
    roots = [
        Path.home() / "Desktop",
        Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop",
        Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
    ]
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for base in roots:
        if not base.exists():
            continue
        try:
            iterator = base.rglob("*")
        except Exception:
            continue
        for item in iterator:
            if not item.is_file() or item.suffix.casefold() not in {".lnk", ".url"}:
                continue
            key = str(item).casefold()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": item.stem, "path": str(item), "source": "shortcut"})
    return rows


def _start_apps() -> list[dict[str, str]]:
    script = """
$ErrorActionPreference='SilentlyContinue'
Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress
"""
    result = _ps(script)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except Exception:
        return []
    if isinstance(data, dict):
        data = [data]
    rows = []
    for item in data if isinstance(data, list) else []:
        name = str(item.get("Name", "")).strip()
        appid = str(item.get("AppID", "")).strip()
        if name and appid:
            rows.append({"name": name, "appid": appid, "source": "start_app"})
    return rows


def installed_apps() -> list[dict[str, str]]:
    _require_windows()
    rows = _desktop_shortcuts() + _start_apps()
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        target = item.get("path") or item.get("appid") or ""
        key = (_normalize_name(item.get("name", "")), target.casefold())
        if not key[0] or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _score_app(query: str, candidate: str) -> int:
    q = _normalize_name(query)
    c = _normalize_name(candidate)
    if not q or not c:
        return -1
    if q == c:
        return 1000
    if c.startswith(q):
        return 850 - (len(c) - len(q))
    if q in c:
        return 700 - (len(c) - len(q))
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    overlap = len(q_tokens & c_tokens)
    if overlap:
        return overlap * 100 - abs(len(q_tokens) - len(c_tokens))
    return -1


def resolve_app(app: str) -> dict[str, str] | None:
    value = app.strip()
    if not value:
        return None

    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if expanded.exists():
        return {"name": expanded.stem, "path": str(expanded), "source": "path"}

    executable = shutil.which(value) or shutil.which(value + ".exe")
    if executable:
        return {"name": Path(executable).stem, "path": executable, "source": "path"}

    aliases = {
        "calculator": "calc.exe",
        "calc": "calc.exe",
        "notepad": "notepad.exe",
        "paint": "mspaint.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "command prompt": "cmd.exe",
        "cmd": "cmd.exe",
        "powershell": "powershell.exe",
        "task manager": "taskmgr.exe",
    }
    if value.casefold() in aliases:
        return {"name": value, "path": aliases[value.casefold()], "source": "alias"}

    apps = installed_apps()
    ranked = sorted(
        ((_score_app(value, item["name"]), item) for item in apps),
        key=lambda pair: pair[0],
        reverse=True,
    )
    if ranked and ranked[0][0] >= 100:
        return ranked[0][1]
    return None


def open_app(app: str) -> dict[str, Any]:
    _require_windows()
    resolved = resolve_app(app)
    if resolved is None:
        raise SystemControlError(f"I couldn't find an installed app matching {app!r}.")

    if resolved["source"] in {"shortcut", "path", "alias"}:
        _shell_open_detached(resolved["path"])
    else:
        launch_detached_process(
            ["explorer.exe", f"shell:AppsFolder\\{resolved['appid']}"]
        )
    return {"requested": app, "name": resolved["name"], "source": resolved["source"], "opened": True}


def open_apps(apps: list[str]) -> dict[str, Any]:
    results, errors = [], []
    for app in apps:
        try:
            results.append(open_app(app))
        except Exception as exc:
            errors.append({"app": app, "error": str(exc)})
    return {"opened": results, "errors": errors}


def _running_windows_processes() -> list[dict[str, Any]]:
    script = """
$ErrorActionPreference='SilentlyContinue'
Get-Process | ForEach-Object {
  [PSCustomObject]@{
    Id=$_.Id
    ProcessName=$_.ProcessName
    MainWindowTitle=$_.MainWindowTitle
    MainWindowHandle=$_.MainWindowHandle
    Path=$_.Path
  }
} | ConvertTo-Json -Compress
"""
    result = _ps(script)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except Exception:
        return []
    return [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])


def find_running_app(app: str) -> list[dict[str, Any]]:
    q = _normalize_name(app)
    if not q:
        return []
    aliases = {
        "opera gx": {"opera"}, "opera": {"opera"}, "chrome": {"chrome"},
        "google chrome": {"chrome"}, "discord": {"discord"}, "whatsapp": {"whatsapp"},
        "spotify": {"spotify"}, "steam": {"steam"}, "calculator": {"calculatorapp", "calculator"},
        "notepad": {"notepad"}, "task manager": {"taskmgr"},
    }
    process_aliases = aliases.get(q, {q.replace(" ", "")})
    matched = []
    for item in _running_windows_processes():
        pname = _normalize_name(str(item.get("ProcessName", ""))).replace(" ", "")
        title = _normalize_name(str(item.get("MainWindowTitle", "")))
        path = _normalize_name(str(item.get("Path", "")))
        if pname in process_aliases or any(alias in pname for alias in process_aliases) or q in title or q in path:
            matched.append(item)
    return matched


def close_app(app: str) -> dict[str, Any]:
    _require_windows()
    matches = find_running_app(app)
    if not matches:
        return {"requested": app, "was_running": False, "closed": False, "message": f"{app} is not open."}

    # Prefer processes that own a real application window. This avoids killing
    # Chromium/Opera renderer/helper processes merely because they share the same
    # executable name. Tray-only apps fall back to their matching processes.
    window_matches = [x for x in matches if int(x.get("MainWindowHandle") or 0) != 0]
    close_targets = window_matches or matches
    pids = sorted({int(x["Id"]) for x in close_targets if x.get("Id")})
    script = (
        "$ids=@(" + ",".join(str(pid) for pid in pids) + ");"
        "foreach($id in $ids){$p=Get-Process -Id $id -ErrorAction SilentlyContinue;"
        "if($p){if($p.MainWindowHandle -ne 0){[void]$p.CloseMainWindow()}"
        "else {Stop-Process -Id $id -ErrorAction SilentlyContinue}}}"
    )
    _ps(script)
    remaining = []
    for _ in range(4):
        time.sleep(0.25)
        remaining = find_running_app(app)
        if not remaining:
            break
    return {
        "requested": app,
        "was_running": True,
        "closed": not bool(remaining),
        "pids": pids,
        "remaining_processes": [x.get("ProcessName") for x in remaining],
        "message": f"Closed {app}." if not remaining else f"Asked {app} to close, but it is still running or waiting for user input.",
    }


def close_apps(apps: list[str]) -> dict[str, Any]:
    return {"results": [close_app(app) for app in apps]}


def volume_get() -> int:
    _require_windows()
    try:
        from pycaw.pycaw import AudioUtilities
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        return int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
    except Exception as exc:
        raise SystemControlError(f"Could not read system volume: {exc}") from exc


def volume_set(value: int) -> int:
    _require_windows()
    level = max(0, min(int(value), 100))
    try:
        from pycaw.pycaw import AudioUtilities
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
        return level
    except Exception as exc:
        raise SystemControlError(f"Could not set system volume: {exc}") from exc


def mute_set(muted: bool = True) -> bool:
    _require_windows()
    try:
        from pycaw.pycaw import AudioUtilities
        endpoint = AudioUtilities.GetSpeakers().EndpointVolume
        endpoint.SetMute(1 if muted else 0, None)
        return bool(muted)
    except Exception as exc:
        raise SystemControlError(f"Could not change mute state: {exc}") from exc


def volume_change(delta: int) -> int:
    return volume_set(volume_get() + int(delta))


def brightness_get() -> int:
    result = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1 -ExpandProperty CurrentBrightness)")
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemControlError("Brightness control is not available for this display.")
    return int(result.stdout.strip().splitlines()[-1])


def brightness_set(value: int) -> int:
    level = max(0, min(int(value), 100))
    script = (
        "$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1;"
        f"if($m){{Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=0;Brightness={level}}} | Out-Null}} else {{exit 3}}"
    )
    result = _ps(script)
    if result.returncode != 0:
        raise SystemControlError("Brightness control is not available for this display.")
    return level


def brightness_change(delta: int) -> int:
    return brightness_set(brightness_get() + int(delta))


def wifi_adapters() -> list[dict[str, str]]:
    script = """
$ErrorActionPreference='SilentlyContinue'
Get-NetAdapter | Where-Object {
 $_.Name -match 'Wi-?Fi|Wireless' -or $_.InterfaceDescription -match 'Wireless|Wi-?Fi|802\\.11'
} | Select-Object Name,Status,InterfaceDescription | ConvertTo-Json -Compress
"""
    result = _ps(script)
    if not result.stdout.strip():
        return []
    try:
        data = json.loads(result.stdout)
    except Exception:
        return []
    return [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])


def wifi_status() -> dict[str, Any]:
    adapters = wifi_adapters()
    enabled = any(str(x.get("Status", "")).casefold() not in {"disabled", "not present"} for x in adapters)
    connected = any(str(x.get("Status", "")).casefold() == "up" for x in adapters)
    return {"enabled": enabled, "connected": connected, "adapters": adapters}


def wifi_toggle(enabled: bool | None = None) -> dict[str, Any]:
    status = wifi_status()
    target = (not status["enabled"]) if enabled is None else bool(enabled)
    adapters = status["adapters"]
    if not adapters:
        raise SystemControlError("No Wi-Fi adapter was found.")
    verb = "Enable-NetAdapter" if target else "Disable-NetAdapter"
    names = [str(x.get("Name", "")) for x in adapters if x.get("Name")]
    quoted = ",".join("'" + x.replace("'", "''") + "'" for x in names)
    result = _ps(f"$names=@({quoted}); foreach($n in $names){{{verb} -Name $n -Confirm:$false -ErrorAction Stop}}")
    if result.returncode != 0:
        raise SystemControlError("Windows denied the Wi-Fi change. This action may require administrator permission.")
    time.sleep(0.4)
    return wifi_status()


def dark_mode_get() -> bool:
    result = _ps("(Get-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name AppsUseLightTheme -ErrorAction SilentlyContinue).AppsUseLightTheme")
    value = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else "1"
    return value == "0"


def dark_mode_set(enabled: bool) -> bool:
    light = 0 if enabled else 1
    script = (
        "$p='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize';"
        "New-Item -Path $p -Force | Out-Null;"
        f"Set-ItemProperty -Path $p -Name AppsUseLightTheme -Type DWord -Value {light};"
        f"Set-ItemProperty -Path $p -Name SystemUsesLightTheme -Type DWord -Value {light};"
    )
    result = _ps(script)
    if result.returncode != 0:
        raise SystemControlError("Could not change Windows theme mode.")
    return bool(enabled)


def lock_screen() -> None:
    _require_windows()
    if not ctypes.windll.user32.LockWorkStation():
        raise SystemControlError("Windows did not accept the lock-screen request.")


def restart_computer() -> None:
    _require_windows()
    subprocess.Popen(["shutdown", "/r", "/t", "0"])


def shutdown_computer() -> None:
    _require_windows()
    subprocess.Popen(["shutdown", "/s", "/t", "0"])


def sleep_display() -> None:
    _require_windows()
    ctypes.windll.user32.SendMessageW(0xFFFF, 0x0112, 0xF170, 2)


def open_settings(page: str = "") -> None:
    _require_windows()
    os.startfile("ms-settings:" + page.strip().lstrip(":"))  # type: ignore[attr-defined]


def open_task_manager() -> None:
    _require_windows()
    subprocess.Popen(["taskmgr.exe"])


def _hotkey(*keys: str) -> None:
    import pyautogui
    pyautogui.hotkey(*keys)


def show_desktop() -> None:
    _hotkey("win", "d")


def snap_window(direction: str) -> str:
    value = direction.casefold().strip()
    if value not in {"left", "right"}:
        raise SystemControlError("Snap direction must be left or right.")
    _hotkey("win", value)
    return value


def switch_windows() -> None:
    _hotkey("alt", "tab")


def browser_zoom(action: str) -> str:
    value = action.casefold().strip()
    if value in {"in", "up", "increase"}:
        _hotkey("ctrl", "+")
        return "in"
    if value in {"out", "down", "decrease"}:
        _hotkey("ctrl", "-")
        return "out"
    if value in {"reset", "normal", "100"}:
        _hotkey("ctrl", "0")
        return "reset"
    raise SystemControlError("Browser zoom action must be in, out, or reset.")


def browser_tab_shortcut(action: str) -> str:
    value = action.casefold().strip()
    mapping = {
        "next": ("ctrl", "tab"), "previous": ("ctrl", "shift", "tab"),
        "new": ("ctrl", "t"), "close": ("ctrl", "w"), "reopen": ("ctrl", "shift", "t"),
    }
    keys = mapping.get(value)
    if not keys:
        raise SystemControlError("Browser tab action must be next, previous, new, close, or reopen.")
    _hotkey(*keys)
    return value


def page_navigation(action: str) -> str:
    value = action.casefold().strip()
    if value == "back":
        _hotkey("alt", "left")
    elif value == "forward":
        _hotkey("alt", "right")
    elif value in {"reload", "refresh"}:
        _hotkey("ctrl", "r")
        value = "reload"
    else:
        raise SystemControlError("Page navigation action must be back, forward, or reload.")
    return value
