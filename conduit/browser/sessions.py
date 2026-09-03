"""Unified real-browser discovery and session metadata.

Browser-specific differences live in declarative descriptors. The BrowserEngine
uses one shared implementation for default-browser discovery, native real-profile
windows, Playwright persistent profiles, and supported automation attachments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import time
from typing import Any


@dataclass(frozen=True, slots=True)
class BrowserDescriptor:
    name: str
    aliases: tuple[str, ...]
    family: str
    executable_names: tuple[str, ...]
    executable_candidates: tuple[str, ...]
    private_args: tuple[str, ...] = ()
    profile_args: tuple[str, ...] = ()

    def matches(self, value: str) -> bool:
        key = value.casefold().strip()
        return key == self.name.casefold() or key in {x.casefold() for x in self.aliases}


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


# This is data, not separate browser implementations. New browsers are added by
# adding a descriptor; the session logic remains unchanged.
BROWSERS: tuple[BrowserDescriptor, ...] = (
    BrowserDescriptor(
        "chrome", ("google chrome",), "chromium",
        ("chrome.exe", "chrome"),
        (
            r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
            r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        ),
        ("--incognito",),
    ),
    BrowserDescriptor(
        "edge", ("microsoft edge", "msedge"), "chromium",
        ("msedge.exe", "microsoft-edge", "microsoft-edge-stable"),
        (
            r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
            r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
        ),
        ("--inprivate",),
    ),
    BrowserDescriptor(
        "opera", ("opera stable",), "chromium",
        ("opera.exe", "opera"),
        (
            r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
            r"%LOCALAPPDATA%\Programs\Opera\launcher.exe",
            r"%PROGRAMFILES%\Opera\opera.exe",
            r"%PROGRAMFILES%\Opera\launcher.exe",
            "/Applications/Opera.app/Contents/MacOS/Opera",
            "/usr/bin/opera",
        ),
        ("--private",),
    ),
    BrowserDescriptor(
        "opera gx", ("operagx", "opera_gx", "gx"), "chromium",
        ("opera.exe",),
        (
            r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe",
            r"%LOCALAPPDATA%\Programs\Opera GX\launcher.exe",
        ),
        ("--private",),
    ),
    BrowserDescriptor(
        "brave", ("brave browser",), "chromium",
        ("brave.exe", "brave-browser", "brave-browser-stable"),
        (
            r"%PROGRAMFILES%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%PROGRAMFILES(X86)%\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/usr/bin/brave-browser", "/usr/bin/brave-browser-stable",
        ),
        ("--incognito",),
    ),
    BrowserDescriptor(
        "vivaldi", ("vivaldi browser",), "chromium",
        ("vivaldi.exe", "vivaldi"),
        (
            r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",
            r"%PROGRAMFILES%\Vivaldi\Application\vivaldi.exe",
            "/Applications/Vivaldi.app/Contents/MacOS/Vivaldi",
            "/usr/bin/vivaldi",
        ),
        ("--incognito",),
    ),
    BrowserDescriptor(
        "firefox", ("mozilla firefox",), "firefox",
        ("firefox.exe", "firefox"),
        (
            r"%PROGRAMFILES%\Mozilla Firefox\firefox.exe",
            r"%PROGRAMFILES(X86)%\Mozilla Firefox\firefox.exe",
            "/Applications/Firefox.app/Contents/MacOS/firefox",
            "/usr/bin/firefox",
        ),
        ("-private-window",),
    ),
    BrowserDescriptor(
        "safari", ("apple safari",), "webkit",
        ("Safari",),
        ("/Applications/Safari.app/Contents/MacOS/Safari",),
        ("-Private",),
    ),
)


@dataclass(slots=True)
class BrowserSession:
    session_id: str
    browser_name: str
    family: str
    mode: str
    transport: str
    executable: str = ""
    profile_name: str = ""
    profile_path: str = ""
    private: bool = False
    pid: int | None = None
    endpoint: str = ""
    created_at: float = field(default_factory=time.time)
    browser: Any = None
    context: Any = None
    page: Any = None
    native_hwnd: int = 0

    def data(self, *, active: bool = False) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "browser": self.browser_name,
            "family": self.family,
            "mode": self.mode,
            "transport": self.transport,
            "profile_name": self.profile_name,
            "profile_path": self.profile_path,
            "private": self.private,
            "pid": self.pid,
            "endpoint": self.endpoint,
            "active": active,
            "automation_available": self.transport in {"playwright", "cdp"},
        }


def resolve_descriptor(name: str) -> BrowserDescriptor:
    value = (name or "").strip()
    for item in BROWSERS:
        if item.matches(value):
            return item
    raise ValueError(f"Unsupported browser name: {name!r}.")


def executable_for(descriptor: BrowserDescriptor) -> str | None:
    for candidate in descriptor.executable_candidates:
        path = _expand(candidate)
        if path.is_file():
            return str(path)
    for name in descriptor.executable_names:
        found = shutil.which(name)
        if found:
            return found
    return None


def installed_browsers() -> list[dict[str, str]]:
    result = []
    for descriptor in BROWSERS:
        executable = executable_for(descriptor)
        if executable:
            result.append({
                "name": descriptor.name,
                "family": descriptor.family,
                "executable": executable,
            })
    return result


def _windows_default_browser_command() -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
        for hive in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
            try:
                path = rf"{prog_id}\shell\open\command"
                with winreg.OpenKey(hive, path) as key:
                    command, _ = winreg.QueryValueEx(key, None)
                if command:
                    return str(command)
            except OSError:
                continue
    except Exception:
        return ""
    return ""


def default_browser_descriptor() -> BrowserDescriptor:
    command = _windows_default_browser_command().casefold()
    if command:
        normalized_command = command.replace("/", "\\")

        # First compare the exact executable paths of browsers that are actually
        # installed. This is essential for Opera vs Opera GX because both may
        # ultimately launch through a file named opera.exe/launcher.exe.
        for descriptor in BROWSERS:
            executable = executable_for(descriptor)
            if not executable:
                continue
            normalized_executable = str(Path(executable)).casefold().replace("/", "\\")
            if normalized_executable and normalized_executable in normalized_command:
                return descriptor

        # Then use vendor/path signatures. Check the more specific Opera GX
        # signature BEFORE plain Opera so "Opera GX" can never collapse to Opera.
        signatures = (
            ("opera gx", ("opera gx", "operagx")),
            ("chrome", ("google\\chrome", "google/chrome")),
            ("edge", ("microsoft\\edge", "microsoft/edge", "msedge.exe")),
            ("brave", ("bravesoftware", "brave-browser")),
            ("vivaldi", ("vivaldi",)),
            ("firefox", ("mozilla firefox", "firefox.exe")),
            ("opera", ("\\opera\\", "/opera/", "opera stable")),
            ("safari", ("safari",)),
        )
        for browser_name, markers in signatures:
            if any(marker in normalized_command for marker in markers):
                try:
                    return resolve_descriptor(browser_name)
                except ValueError:
                    pass

    # Portable fallback: prefer the first installed browser in descriptor order.
    found = installed_browsers()
    if found:
        return resolve_descriptor(found[0]["name"])
    raise RuntimeError("No supported installed browser could be detected.")


def launch_native(
    descriptor: BrowserDescriptor,
    *,
    url: str = "",
    private: bool = False,
) -> tuple[int | None, str]:
    executable = executable_for(descriptor)
    if not executable:
        raise RuntimeError(f"{descriptor.name.title()} is not installed or could not be located.")
    args = [executable]
    if private:
        args.extend(descriptor.private_args)
    if url:
        args.append(url)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process.pid, executable


def _enum_windows_for_pid(pid: int) -> list[tuple[int, str]]:
    if sys.platform != "win32" or not pid:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    results: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        proc_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        results.append((int(hwnd), buf.value))
        return True

    user32.EnumWindows(callback, 0)
    return results


def _process_executable_path(pid: int) -> str:
    """Return a Windows process image path without third-party dependencies."""
    if sys.platform != "win32" or not pid:
        return ""
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        int(pid),
    )
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(
            handle,
            0,
            buf,
            ctypes.byref(size),
        ):
            return ""
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def browser_windows_by_executable(browser_name: str) -> list[tuple[int, int]]:
    """Return all visible main windows for a browser, ordered by relevance."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    try:
        descriptor = resolve_descriptor(browser_name)
    except Exception:
        return []
    expected = executable_for(descriptor)
    if not expected:
        return []
    expected_norm = str(Path(expected)).casefold().replace("/", "\\")
    expected_name = Path(expected_norm).name
    user32 = ctypes.windll.user32
    foreground = int(user32.GetForegroundWindow() or 0)
    matches: list[tuple[int, int, int, bool]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):
            return True
        if user32.GetWindowTextLengthW(hwnd) <= 0:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return True
        actual = _process_executable_path(int(pid.value))
        if not actual:
            return True
        actual_norm = actual.casefold().replace("/", "\\")
        actual_name = Path(actual_norm).name
        exact = actual_norm == expected_norm
        if descriptor.name == "opera gx":
            family_match = "\\opera gx\\" in actual_norm and actual_name in {"opera.exe","launcher.exe"}
        elif descriptor.name == "opera":
            family_match = "\\opera\\" in actual_norm and "\\opera gx\\" not in actual_norm and actual_name in {"opera.exe","launcher.exe"}
        else:
            family_match = actual_name == expected_name
        if not (exact or family_match):
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        width=max(0,int(rect.right-rect.left)); height=max(0,int(rect.bottom-rect.top))
        if width < 400 or height < 250:
            return True
        matches.append((int(hwnd),int(pid.value),width*height,int(hwnd)==foreground))
        return True

    user32.EnumWindows(callback,0)
    matches.sort(key=lambda item:(item[3],item[2]), reverse=True)
    return [(hwnd,pid) for hwnd,pid,_area,_fg in matches]

def _find_browser_window_by_executable(browser_name: str) -> tuple[int,int] | None:
    # _process_executable_path is used by browser_windows_by_executable().
    windows=browser_windows_by_executable(browser_name)
    return windows[0] if windows else None


def _force_foreground_window(hwnd: int) -> bool:
    """Focus a real browser window without changing its normal geometry."""
    if sys.platform != "win32" or not hwnd:
        return False

    import ctypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    try:
        if not user32.IsWindow(hwnd):
            return False

        if bool(user32.IsIconic(hwnd)):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE only for minimized windows

        foreground = int(user32.GetForegroundWindow() or 0)
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground, None) or 0)
            if foreground else 0
        )
        current_thread = int(kernel32.GetCurrentThreadId() or 0)

        attached = []

        def attach(a: int, b: int) -> None:
            if a and b and a != b and user32.AttachThreadInput(a, b, True):
                attached.append((a, b))

        attach(current_thread, foreground_thread)
        attach(current_thread, target_thread)
        attach(foreground_thread, target_thread)

        try:
            user32.BringWindowToTop(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for a, b in reversed(attached):
                user32.AttachThreadInput(a, b, False)

        if int(user32.GetForegroundWindow() or 0) == int(hwnd):
            return True

        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)

        return int(user32.GetForegroundWindow() or 0) == int(hwnd)
    except Exception:
        return False


def focus_native_session(session: BrowserSession) -> bool:
    """Resolve and focus the user's real browser without resizing it."""
    if sys.platform != "win32":
        return False

    import ctypes
    user32 = ctypes.windll.user32
    hwnd = int(session.native_hwnd or 0)

    if hwnd and not user32.IsWindow(hwnd):
        hwnd = 0
        session.native_hwnd = 0

    if not hwnd and session.pid:
        windows = _enum_windows_for_pid(session.pid)
        if windows:
            best_hwnd = 0
            best_area = -1
            for candidate_hwnd, _title in windows:
                rect = ctypes.wintypes.RECT()
                if user32.GetWindowRect(candidate_hwnd, ctypes.byref(rect)):
                    area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
                    if area > best_area:
                        best_area = area
                        best_hwnd = int(candidate_hwnd)
            if best_hwnd:
                hwnd = best_hwnd
                session.native_hwnd = hwnd

    if not hwnd:
        found = _find_browser_window_by_executable(session.browser_name)
        if found:
            hwnd, pid = found
            session.native_hwnd = int(hwnd)
            session.pid = int(pid)

    if not hwnd:
        return False

    return _force_foreground_window(int(hwnd))



def maximize_native_session(session: BrowserSession) -> bool:
    """Reliably maximize the exact visible native browser window.

    Opera GX and some Chromium browsers can ignore an immediate Restore ->
    Maximize sequence while reusing an existing snapped window. This helper
    verifies the real HWND state and retries through Windows' system-command
    path when necessary.
    """
    if sys.platform != "win32":
        return False

    import ctypes
    user32 = ctypes.windll.user32

    if not session.native_hwnd:
        focus_native_session(session)
    hwnd = int(session.native_hwnd or 0)
    if not hwnd:
        return False

    try:
        # If the browser is already maximized, preserve it exactly as-is.
        if bool(user32.IsZoomed(hwnd)):
            user32.SetForegroundWindow(hwnd)
            return True

        # Bring the exact browser window forward first. Do NOT explicitly
        # restore to the snapped geometry before maximizing.
        user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.SetForegroundWindow(hwnd)

        # First attempt: direct asynchronous maximize.
        user32.ShowWindowAsync(hwnd, 3)  # SW_MAXIMIZE
        time.sleep(0.10)
        if bool(user32.IsZoomed(hwnd)):
            return True

        # Chromium/Opera GX can occasionally ignore ShowWindowAsync while a
        # reused window is transitioning. Ask the window itself to maximize.
        WM_SYSCOMMAND = 0x0112
        SC_MAXIMIZE = 0xF030
        user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE, 0)
        time.sleep(0.12)
        if bool(user32.IsZoomed(hwnd)):
            return True

        # Last native fallback: synchronous maximize once the window is focused.
        user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.08)
        return bool(user32.IsZoomed(hwnd))
    except Exception:
        return False


def native_window_title(session: BrowserSession) -> str:
    if sys.platform != "win32":
        return ""
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = int(session.native_hwnd or 0)
    if not hwnd:
        focus_native_session(session)
        hwnd = int(session.native_hwnd or 0)
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(max(1, length + 1))
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value


def native_window_rect(session: BrowserSession) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    if not session.native_hwnd:
        focus_native_session(session)
    if not session.native_hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetWindowRect(int(session.native_hwnd), ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom
