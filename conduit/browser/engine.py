"""Playwright-based managed browser engine."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib.request import urlopen


from conduit.events import EventBus, EventNames

from .errors import BrowserEngineError, BrowserNotStartedError, BrowserTargetError
from .models import BrowserActionResult, BrowserState, BrowserTarget, DownloadResult, TargetKind
from .sessions import (
    BrowserSession,
    browser_windows_by_executable,
    default_browser_descriptor,
    executable_for,
    focus_native_session,
    installed_browsers,
    launch_native,
    native_window_rect,
    native_window_title,
    resolve_descriptor,
)

try:  # Import lazily enough for unit tests and informative setup errors.
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Download,
        Locator,
        Page,
        Playwright,
        async_playwright,
    )
except ImportError:  # pragma: no cover - exercised only before dependency install.
    Browser = BrowserContext = Download = Locator = Page = Playwright = Any  # type: ignore[misc,assignment]
    async_playwright = None  # type: ignore[assignment]


class BrowserEngine:
    """Own a Chromium session and expose semantic browser operations."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        headless: bool = False,
        downloads_dir: str | Path | None = None,
        action_timeout_ms: int = 10_000,
    ) -> None:
        self.events = event_bus
        self.headless = headless
        self.downloads_dir = Path(downloads_dir or Path.cwd() / "downloads").resolve()
        self.action_timeout_ms = action_timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

        # Unified browser-session registry. Existing managed Chromium remains a
        # first-class session; native real-profile and attached sessions coexist.
        self._sessions: dict[str, BrowserSession] = {}
        self._active_session_id: str | None = None
        self._session_counter = 0
        self._profiles_root = (Path.cwd() / ".conduit" / "browser_profiles").resolve()

    @property
    def is_started(self) -> bool:
        return self._page is not None

    @property
    def page(self) -> Page:
        """Return the active Playwright page for high-level capabilities."""
        return self._require_page()

    async def __aenter__(self) -> "BrowserEngine":
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.close()

    async def start(self) -> BrowserActionResult:
        """Start the legacy managed Chromium session.

        This remains the default automation sandbox for tasks that do not ask for
        a real/default browser profile.
        """
        if self.is_started and self._active_session() is not None:
            return BrowserActionResult(True, "start", "Browser session is already running.", await self.state())
        if async_playwright is None:
            raise BrowserEngineError(
                "Playwright is not installed. Run 'py -m pip install -e .' and "
                "'py -m playwright install chromium'."
            )
        await self._emit(EventNames.BROWSER_STARTED, {"headless": self.headless})
        try:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            await self._ensure_playwright()
            assert self._playwright is not None
            browser = await self._playwright.chromium.launch(headless=self.headless)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            page.set_default_timeout(self.action_timeout_ms)
            session = self._register_session(
                BrowserSession(
                    session_id=self._next_session_id("managed"),
                    browser_name="chromium",
                    family="chromium",
                    mode="managed",
                    transport="playwright",
                    browser=browser,
                    context=context,
                    page=page,
                )
            )
            self._select_session(session)
            result = BrowserActionResult(
                True,
                "start",
                "Managed Chromium browser started.",
                await self.state(),
                {"session_id": session.session_id},
            )
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "start", "error": str(exc)})
            await self.close()
            raise BrowserEngineError(f"Unable to start Chromium: {exc}") from exc

    async def close(self) -> None:
        """Release Conduit-owned automation sessions.

        Native real-profile browsers are intentionally left open: they belong to
        the user, not to Conduit. Attached sessions are detached without closing
        the user's browser.
        """
        sessions = list(self._sessions.values())
        self._sessions.clear()
        self._active_session_id = None
        self._page = self._context = self._browser = None

        closed_contexts: set[int] = set()
        closed_browsers: set[int] = set()
        for session in sessions:
            if session.transport == "playwright":
                if session.context is not None and id(session.context) not in closed_contexts:
                    try:
                        await session.context.close()
                    except Exception:
                        pass
                    closed_contexts.add(id(session.context))
                if session.browser is not None and id(session.browser) not in closed_browsers:
                    try:
                        await session.browser.close()
                    except Exception:
                        pass
                    closed_browsers.add(id(session.browser))
            # CDP attachments are deliberately not closed, because closing the
            # connected browser object can terminate the user's real browser.

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        await self._emit(EventNames.BROWSER_CLOSED, {})

    async def new_tab(self, url: str = "about:blank") -> BrowserActionResult:
        """Open a new tab in the active browser session."""
        session = self._active_session()
        if session is None:
            await self.start()
            session = self._active_session()
        assert session is not None
        normalized = self._normalize_url(url) if url != "about:blank" else url

        if session.transport == "native":
            await self._native_focus_or_raise(session)
            self._native_hotkey("ctrl", "t")
            await asyncio.sleep(0.15)
            if normalized != "about:blank":
                self._native_hotkey("ctrl", "l")
                self._native_type(normalized)
                self._native_press("enter")
            return BrowserActionResult(
                True,
                "new_tab",
                f"Opened a new tab in {session.browser_name.title()}.",
                await self.state(),
                {"session_id": session.session_id, "transport": "native"},
            )

        context = session.context or self._context
        if context is None:
            raise BrowserNotStartedError("The active browser session has no automation context.")
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "new_tab", "url": normalized})
        try:
            page = await context.new_page()
            page.set_default_timeout(self.action_timeout_ms)
            session.page = page
            self._page = page
            if normalized != "about:blank":
                await page.goto(normalized, wait_until="domcontentloaded")
            result = BrowserActionResult(
                True, "new_tab", "Opened a new browser tab.", await self.state(),
                {"session_id": session.session_id},
            )
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "new_tab", "url": normalized, "error": str(exc)})
            raise BrowserEngineError(f"Unable to open a new browser tab: {exc}") from exc

    async def goto(self, url: str, *, wait_until: str = "domcontentloaded") -> BrowserActionResult:
        normalized = self._normalize_url(url)
        session = self._active_session()
        if session is not None and session.transport == "native":
            await self._native_focus_or_raise(session)
            self._native_hotkey("ctrl", "l")
            self._native_type(normalized)
            self._native_press("enter")
            await asyncio.sleep(0.15)
            return BrowserActionResult(
                True, "goto", f"Opened {normalized}.", await self.state(),
                {"session_id": session.session_id, "transport": "native"},
            )
        page = self._require_page()
        return await self._run_action(
            "goto",
            {"url": normalized},
            page.goto(normalized, wait_until=wait_until),
            success_message=f"Opened {normalized}.",
        )

    async def click(self, target: BrowserTarget) -> BrowserActionResult:
        locator = self._locator(target)
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "click", "target": self._target_payload(target)})
        try:
            await locator.first.click()
            result = BrowserActionResult(True, "click", f"Clicked {target.value!r}.", await self.state())
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "click", "error": str(exc), "target": self._target_payload(target)})
            raise BrowserTargetError(f"Unable to click target {target.value!r}: {exc}") from exc

    async def fill(self, target: BrowserTarget, text: str) -> BrowserActionResult:
        locator = self._locator(target)
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "fill", "target": self._target_payload(target)})
        try:
            await locator.first.fill(text)
            result = BrowserActionResult(True, "fill", f"Filled {target.value!r}.", await self.state(), {"characters": len(text)})
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "fill", "error": str(exc), "target": self._target_payload(target)})
            raise BrowserTargetError(f"Unable to fill target {target.value!r}: {exc}") from exc

    async def press(self, target: BrowserTarget, key: str) -> BrowserActionResult:
        locator = self._locator(target)
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "press", "key": key, "target": self._target_payload(target)})
        try:
            await locator.first.press(key)
            result = BrowserActionResult(True, "press", f"Pressed {key!r} on {target.value!r}.", await self.state())
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "press", "error": str(exc), "target": self._target_payload(target)})
            raise BrowserTargetError(f"Unable to press {key!r} on target {target.value!r}: {exc}") from exc

    async def press_page(self, key: str) -> BrowserActionResult:
        """Press a key on the active page without requiring a target locator."""
        page = self._require_page()
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "press_page", "key": key})
        try:
            await page.keyboard.press(key)
            result = BrowserActionResult(True, "press_page", f"Pressed {key!r} on the page.", await self.state())
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "press_page", "key": key, "error": str(exc)})
            raise BrowserEngineError(f"Unable to press {key!r} on the page: {exc}") from exc

    async def scroll(self, *, delta_y: int = 700) -> BrowserActionResult:
        page = self._require_page()
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": "scroll", "delta_y": delta_y})
        try:
            await page.mouse.wheel(0, delta_y)
            await asyncio.sleep(0.05)
            result = BrowserActionResult(True, "scroll", f"Scrolled by {delta_y} pixels.", await self.state())
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "scroll", "error": str(exc)})
            raise BrowserEngineError(f"Unable to scroll page: {exc}") from exc

    async def visible_text(self, *, max_characters: int = 20_000) -> str:
        page = self._require_page()
        text = await page.locator("body").inner_text()
        return text[:max_characters]

    async def state(self, *, max_text_characters: int = 8_000) -> BrowserState:
        session = self._active_session()
        if session is not None and session.transport == "native":
            return BrowserState(
                title=native_window_title(session),
                url="",
                visible_text="",
                viewport_width=0,
                viewport_height=0,
            )
        page = self._require_page()
        viewport = page.viewport_size or {"width": 0, "height": 0}
        return BrowserState(
            title=await page.title(),
            url=page.url,
            visible_text=(await self.visible_text(max_characters=max_text_characters)),
            viewport_width=int(viewport.get("width", 0)),
            viewport_height=int(viewport.get("height", 0)),
        )

    async def element_exists(self, target: BrowserTarget) -> bool:
        try:
            return await self._locator(target).count() > 0
        except Exception:
            return False

    async def download(self, target: BrowserTarget, *, filename: str | None = None) -> DownloadResult:
        page = self._require_page()
        locator = self._locator(target)
        await self._emit(EventNames.BROWSER_DOWNLOAD_STARTED, {"target": self._target_payload(target)})
        try:
            async with page.expect_download() as download_info:
                await locator.first.click()
            download: Download = await download_info.value
            chosen_name = filename or download.suggested_filename
            destination = (self.downloads_dir / chosen_name).resolve()
            await download.save_as(destination)
            result = DownloadResult(download.suggested_filename, destination, download.url)
            await self._emit(
                EventNames.BROWSER_DOWNLOAD_COMPLETED,
                {"filename": result.suggested_filename, "saved_path": str(result.saved_path), "url": result.url},
            )
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": "download", "error": str(exc)})
            raise BrowserEngineError(f"Download failed: {exc}") from exc

    async def launch_profile(
        self,
        browser: str = "",
        *,
        profile: str = "Default",
        private: bool = False,
        url: str = "about:blank",
    ) -> BrowserActionResult:
        """Launch a persistent Conduit-owned browser profile.

        This intentionally does not automate Chrome's protected everyday User Data
        directory. The Conduit profile persists logins/cookies across runs once the
        user signs into it.
        """
        descriptor = resolve_descriptor(browser) if browser.strip() else default_browser_descriptor()
        executable = executable_for(descriptor)
        if not executable:
            raise BrowserEngineError(f"{descriptor.name.title()} is not installed.")
        if descriptor.family == "webkit" and sys.platform != "darwin":
            raise BrowserEngineError("Safari profile automation is only available on macOS.")

        if private:
            # Private/incognito is deliberately non-persistent.
            return await self._launch_private_automation(descriptor.name, url=url)

        if async_playwright is None:
            raise BrowserEngineError("Playwright is required for browser profile automation.")
        await self._ensure_playwright()
        assert self._playwright is not None

        safe_profile = "".join(ch for ch in profile if ch.isalnum() or ch in "-_ ").strip() or "Default"
        user_data_dir = self._profiles_root / descriptor.name.replace(" ", "_") / safe_profile
        user_data_dir.mkdir(parents=True, exist_ok=True)

        browser_type = self._playwright.firefox if descriptor.family == "firefox" else self._playwright.chromium
        kwargs: dict[str, Any] = {
            "headless": self.headless,
            "accept_downloads": True,
        }
        # Playwright supports executable_path for branded Chromium browsers.
        if executable:
            kwargs["executable_path"] = executable

        try:
            context = await browser_type.launch_persistent_context(str(user_data_dir), **kwargs)
            pages = list(context.pages)
            page = pages[0] if pages else await context.new_page()
            page.set_default_timeout(self.action_timeout_ms)
            if url and url != "about:blank":
                await page.goto(self._normalize_url(url), wait_until="domcontentloaded")
            session = self._register_session(BrowserSession(
                session_id=self._next_session_id(descriptor.name),
                browser_name=descriptor.name,
                family=descriptor.family,
                mode="profile",
                transport="playwright",
                executable=executable,
                profile_name=safe_profile,
                profile_path=str(user_data_dir),
                private=False,
                context=context,
                page=page,
            ))
            self._select_session(session)
            return BrowserActionResult(
                True, "launch_profile",
                f"Opened persistent {descriptor.name.title()} Conduit profile {safe_profile!r}.",
                await self.state(),
                session.data(active=True),
            )
        except Exception as exc:
            raise BrowserEngineError(
                f"Unable to launch {descriptor.name.title()} persistent profile: {exc}"
            ) from exc

    async def _launch_private_automation(
        self,
        browser: str = "",
        *,
        url: str = "about:blank",
    ) -> BrowserActionResult:
        descriptor = resolve_descriptor(browser) if browser.strip() else default_browser_descriptor()
        executable = executable_for(descriptor)
        if not executable:
            raise BrowserEngineError(f"{descriptor.name.title()} is not installed.")
        if async_playwright is None:
            raise BrowserEngineError("Playwright is required for private browser automation.")
        await self._ensure_playwright()
        assert self._playwright is not None
        if descriptor.family == "firefox":
            browser_obj = await self._playwright.firefox.launch(
                headless=self.headless, executable_path=executable
            )
        elif descriptor.family == "webkit":
            if sys.platform != "darwin":
                raise BrowserEngineError("Safari automation is only supported on macOS.")
            browser_obj = await self._playwright.webkit.launch(headless=self.headless)
        else:
            browser_obj = await self._playwright.chromium.launch(
                headless=self.headless, executable_path=executable
            )
        context = await browser_obj.new_context(accept_downloads=True)
        page = await context.new_page()
        page.set_default_timeout(self.action_timeout_ms)
        if url and url != "about:blank":
            await page.goto(self._normalize_url(url), wait_until="domcontentloaded")
        session = self._register_session(BrowserSession(
            session_id=self._next_session_id(descriptor.name),
            browser_name=descriptor.name,
            family=descriptor.family,
            mode="private",
            transport="playwright",
            executable=executable,
            private=True,
            browser=browser_obj,
            context=context,
            page=page,
        ))
        self._select_session(session)
        return BrowserActionResult(
            True, "launch_profile",
            f"Opened private {descriptor.name.title()} automation session.",
            await self.state(),
            session.data(active=True),
        )

    async def ensure_native_browser_session(
        self,
        *,
        browser: str = "",
    ) -> BrowserSession:
        """Adopt/focus an already-running real browser for tab operations."""
        descriptor = resolve_descriptor(browser) if browser.strip() else default_browser_descriptor()
        matches = [
            item for item in self._sessions.values()
            if item.transport == "native" and item.browser_name == descriptor.name
        ]
        session = matches[-1] if matches else BrowserSession(
            session_id=self._next_session_id(descriptor.name),
            browser_name=descriptor.name,
            family=descriptor.family,
            mode="real_profile",
            transport="native",
            executable=executable_for(descriptor) or "",
            private=False,
            pid=None,
        )
        session.native_hwnd = 0
        if not focus_native_session(session):
            raise BrowserEngineError(
                f"I couldn't find or focus an existing {descriptor.name.title()} window."
            )
        session = self._register_session(session)
        self._select_session(session)
        return session

    async def new_tab_focus_only(
        self,
        *,
        browser: str = "",
    ) -> BrowserActionResult:
        """Focus the existing real browser and press Ctrl+T. Nothing else."""
        session = await self.ensure_native_browser_session(browser=browser)
        self._native_hotkey("ctrl", "t")
        await asyncio.sleep(0.10)
        return BrowserActionResult(
            True,
            "new_tab",
            f"Opened a new tab in {session.browser_name.title()}.",
            await self.state(),
            session.data(active=True),
        )


    async def new_tab_real_profile(
        self,
        *,
        browser: str = "",
        private: bool = False,
    ) -> BrowserActionResult:
        """Open a real-browser tab using the same OS/browser handoff as site opens.

        Chromium-family browsers are single-instance applications in normal use.
        Launching their executable with a URL while they are already running
        forwards that URL to the existing browser instance and opens a tab there.
        This deliberately avoids Conduit's HWND/focus/resize logic.
        """
        descriptor = (
            resolve_descriptor(browser)
            if browser.strip()
            else default_browser_descriptor()
        )

        # Unlike use_default_profile(), keep about:blank as an explicit URL.
        # Starting the executable with no URL can create a separate browser
        # window; an explicit URL is handed to the existing browser just like
        # working "open reddit/open gmail" commands.
        pid, executable = launch_native(
            descriptor,
            url="about:blank",
            private=private,
        )

        # Refresh/reuse the logical session registry without touching the actual
        # browser window geometry.
        session = self._register_session(BrowserSession(
            session_id=self._next_session_id(descriptor.name),
            browser_name=descriptor.name,
            family=descriptor.family,
            mode="real_profile_private" if private else "real_profile",
            transport="native",
            executable=executable,
            private=private,
            pid=pid,
        ))
        self._select_session(session)

        return BrowserActionResult(
            True,
            "new_tab",
            f"Opened a new tab in {descriptor.name.title()}.",
            None,
            session.data(active=True),
        )

    async def activate_real_profile(
        self,
        *,
        browser: str = "",
        private: bool = False,
        launch_if_missing: bool = True,
    ) -> BrowserActionResult:
        """Reuse/adopt an existing real browser window before launching one."""
        descriptor = (
            resolve_descriptor(browser)
            if browser.strip()
            else default_browser_descriptor()
        )

        # Reuse a native session Conduit already knows.
        candidates = [
            item for item in self._sessions.values()
            if (
                item.transport == "native"
                and item.browser_name == descriptor.name
                and bool(item.private) == bool(private)
            )
        ]
        for session in reversed(candidates):
            if focus_native_session(session):
                self._select_session(session)
                return BrowserActionResult(
                    True,
                    "activate_real_profile",
                    f"Activated existing {descriptor.name.title()} window.",
                    await self.state(),
                    session.data(active=True),
                )

            # Recover if the saved HWND is stale.
            session.native_hwnd = 0
            if focus_native_session(session):
                self._select_session(session)
                return BrowserActionResult(
                    True,
                    "activate_real_profile",
                    f"Rediscovered existing {descriptor.name.title()} window.",
                    await self.state(),
                    session.data(active=True),
                )

        # Adopt a browser already running before Conduit started.
        adopted = BrowserSession(
            session_id=self._next_session_id(descriptor.name),
            browser_name=descriptor.name,
            family=descriptor.family,
            mode="real_profile_private" if private else "real_profile",
            transport="native",
            executable=executable_for(descriptor) or "",
            private=private,
            pid=None,
        )
        if focus_native_session(adopted):
            adopted = self._register_session(adopted)
            self._select_session(adopted)
            return BrowserActionResult(
                True,
                "activate_real_profile",
                f"Adopted already-running {descriptor.name.title()} window.",
                await self.state(),
                adopted.data(active=True),
            )

        if not launch_if_missing:
            raise BrowserEngineError(
                f"I couldn't find a running {descriptor.name.title()} window."
            )

        # Only now create a new browser window.
        return await self.use_default_profile(
            browser=descriptor.name,
            url="about:blank",
            private=private,
        )

    async def use_default_profile(
        self,
        *,
        browser: str = "",
        url: str = "about:blank",
        private: bool = False,
    ) -> BrowserActionResult:
        """Open the user's real normal browser profile natively.

        Native mode preserves the user's actual accounts, cookies, extensions and
        preferences. DOM-level automation is available only after a supported
        debugging attachment is explicitly enabled.
        """
        descriptor = resolve_descriptor(browser) if browser.strip() else default_browser_descriptor()
        normalized = "" if url == "about:blank" else self._normalize_url(url)
        pid, executable = launch_native(descriptor, url=normalized, private=private)
        session = self._register_session(BrowserSession(
            session_id=self._next_session_id(descriptor.name),
            browser_name=descriptor.name,
            family=descriptor.family,
            mode="real_profile_private" if private else "real_profile",
            transport="native",
            executable=executable,
            private=private,
            pid=pid,
        ))
        self._select_session(session)
        await asyncio.sleep(0.2)
        focus_native_session(session)
        # A real browser may reuse an already-running window that Windows left
        # snapped to half the desktop. Normalize the visible browsing experience
        # by maximizing the selected real-profile window after activation.
        return BrowserActionResult(
            True, "use_default_profile",
            f"Opened the user's real {descriptor.name.title()} profile"
            + (" in private mode." if private else "."),
            await self.state(),
            session.data(active=True),
        )

    async def attach_existing(
        self,
        browser: str = "",
        *,
        endpoint: str = "",
    ) -> BrowserActionResult:
        """Attach to an existing Chromium-family browser over CDP.

        The browser must already expose a debugging endpoint. Modern Chrome
        requires the user to explicitly enable remote debugging for the real
        profile; Conduit never bypasses that security boundary.
        """
        descriptor = resolve_descriptor(browser) if browser.strip() else default_browser_descriptor()
        if descriptor.family != "chromium":
            raise BrowserEngineError(
                f"Existing-session attachment for {descriptor.name.title()} is not "
                "integrated yet. Native real-profile control is still available."
            )
        if async_playwright is None:
            raise BrowserEngineError("Playwright is required for browser attachment.")
        await self._ensure_playwright()
        assert self._playwright is not None

        endpoints = [endpoint.strip()] if endpoint.strip() else [
            f"http://127.0.0.1:{port}" for port in range(9222, 9231)
        ]
        last_error = ""
        for candidate in endpoints:
            try:
                # Fast endpoint probe avoids long Playwright timeouts on closed ports.
                with urlopen(candidate.rstrip("/") + "/json/version", timeout=0.25) as response:
                    json.loads(response.read().decode("utf-8", errors="replace"))
                browser_obj = await self._playwright.chromium.connect_over_cdp(candidate)
                contexts = list(browser_obj.contexts)
                if not contexts:
                    last_error = f"{candidate} exposed no browser context."
                    continue
                context = contexts[0]
                pages = list(context.pages)
                page = pages[0] if pages else await context.new_page()
                page.set_default_timeout(self.action_timeout_ms)
                session = self._register_session(BrowserSession(
                    session_id=self._next_session_id(descriptor.name),
                    browser_name=descriptor.name,
                    family=descriptor.family,
                    mode="attached",
                    transport="cdp",
                    executable=executable_for(descriptor) or "",
                    endpoint=candidate,
                    browser=browser_obj,
                    context=context,
                    page=page,
                ))
                self._select_session(session)
                return BrowserActionResult(
                    True, "attach_existing",
                    f"Attached to existing {descriptor.name.title()} session.",
                    await self.state(),
                    session.data(active=True),
                )
            except Exception as exc:
                last_error = str(exc)
        raise BrowserEngineError(
            f"I couldn't attach to an existing {descriptor.name.title()} automation "
            "endpoint. The browser can still be used in native real-profile mode. "
            f"Last attachment error: {last_error or 'no debugging endpoint found'}"
        )

    async def list_sessions(self) -> BrowserActionResult:
        data = [
            session.data(active=session.session_id == self._active_session_id)
            for session in self._sessions.values()
        ]
        return BrowserActionResult(
            True, "list_sessions",
            f"Found {len(data)} browser session(s).",
            await self.state() if self._active_session() else None,
            {"sessions": data},
        )

    async def switch_session(self, session_id: str) -> BrowserActionResult:
        session = self._sessions.get(session_id.strip())
        if session is None:
            raise BrowserEngineError(f"Unknown browser session: {session_id!r}.")
        self._select_session(session)
        if session.transport == "native":
            await self._native_focus_or_raise(session)
        elif session.page is not None:
            await session.page.bring_to_front()
        return BrowserActionResult(
            True, "switch_session",
            f"Switched to browser session {session.session_id}.",
            await self.state(),
            session.data(active=True),
        )

    async def list_tabs(self) -> BrowserActionResult:
        session=self._require_active_session()
        if session.transport=="native":
            tabs=await self._native_collect_all_tabs(session)
            return BrowserActionResult(
                True,"list_tabs",f"Found {len(tabs)} browser tab(s).",await self.state(),
                {"session_id":session.session_id,"tabs":tabs,"complete":True,
                 "inventory":"native_window_titles"},
            )
        context=session.context
        if context is None:
            raise BrowserEngineError("The active session has no browser context.")
        pages=list(context.pages); tabs=[]
        for number,page in enumerate(pages,start=1):
            try: title=await page.title()
            except Exception: title=""
            tabs.append({"index":number,"title":title,"url":page.url,"active":page is session.page})
        return BrowserActionResult(True,"list_tabs",f"Found {len(tabs)} tab(s).",await self.state(),
                                   {"session_id":session.session_id,"tabs":tabs,"complete":True})

    async def switch_tab(self, tab: int | str) -> BrowserActionResult:
        session=self._require_active_session()
        if session.transport=="native":
            tabs=await self._native_collect_all_tabs(session)
            value=str(tab).strip()
            if value.isdigit():
                number=int(value)
                if not tabs:
                    # Compatibility fallback for a registered native session when
                    # structured inventory is temporarily unavailable.
                    if number < 1:
                        raise BrowserEngineError("Tab numbers start at 1.")
                    key="9" if number>=9 else str(number)
                    await self._native_focus_or_raise(session)
                    self._native_hotkey("ctrl",key)
                    await asyncio.sleep(0.10)
                    return BrowserActionResult(True,"switch_tab",
                        f"Switched {session.browser_name.title()} to tab {number}.",
                        await self.state(),{"session_id":session.session_id,"tab":number})
                match=next((x for x in tabs if x["index"]==number),None)
                if match is None:
                    raise BrowserEngineError(
                        f"{session.browser_name.title()} currently has {len(tabs)} tab(s), "
                        f"so tab {number} doesn't exist."
                    )
            else:
                wanted=value.casefold()
                match=next(
                    (x for x in tabs if wanted in str(x.get("title", "")).casefold()),
                    None,
                )
                if match is None:
                    match=next((x for x in tabs if self._native_tab_matches(x, wanted)),None)
                if match is None:
                    raise BrowserEngineError(
                        f"I couldn't find a {session.browser_name.title()} tab matching {value!r}."
                    )
            await self._native_activate_inventory_tab(session,match)
            return BrowserActionResult(True,"switch_tab",
                f"Switched to {match.get('title') or value} in {session.browser_name.title()}.",
                await self.state(),{"session_id":session.session_id,"tab":match["index"],
                                    "title":match.get("title","")})

        context=session.context
        if context is None: raise BrowserEngineError("The active session has no browser context.")
        pages=list(context.pages); target_page=None
        if isinstance(tab,int) or str(tab).isdigit():
            number=int(tab); index=number-1
            if number<1 or index>=len(pages): raise BrowserEngineError(f"Tab number {number} is out of range.")
            target_page=pages[index]
        else:
            wanted=str(tab).casefold()
            for page in pages:
                try: title=await page.title()
                except Exception: title=""
                if wanted in title.casefold() or wanted in page.url.casefold():
                    target_page=page; break
        if target_page is None: raise BrowserEngineError(f"No browser tab matched {tab!r}.")
        session.page=target_page; self._page=target_page
        await target_page.bring_to_front()
        return BrowserActionResult(True,"switch_tab",f"Switched to tab {tab!r}.",
                                   await self.state(),{"session_id":session.session_id})

    async def close_tab(self, tab: int | str | None = None) -> BrowserActionResult:
        session=self._require_active_session()
        if session.transport=="native":
            if tab is None:
                await self._native_focus_or_raise(session)
            else:
                await self.switch_tab(tab); await asyncio.sleep(0.08)
            self._native_hotkey("ctrl","w"); await asyncio.sleep(0.12)
            return BrowserActionResult(True,"close_tab",
                f"Closed {'tab '+str(tab) if tab is not None else 'the active tab'} in {session.browser_name.title()}.",
                await self.state(),{"session_id":session.session_id})

        context=session.context
        if context is None: raise BrowserEngineError("The active session has no browser context.")
        pages=list(context.pages)
        if not pages: raise BrowserEngineError("There are no browser tabs to close.")
        page=session.page or pages[-1]
        if tab is not None:
            if isinstance(tab,int) or str(tab).isdigit():
                number=int(tab); index=number-1
                if number<1 or index>=len(pages): raise BrowserEngineError(f"Tab number {number} is out of range.")
                page=pages[index]
            else:
                wanted=str(tab).casefold(); matches=[]
                for item in pages:
                    try: title=await item.title()
                    except Exception: title=""
                    if wanted in title.casefold() or wanted in item.url.casefold(): matches.append(item)
                if not matches: raise BrowserEngineError(f"No browser tab matched {tab!r}.")
                page=matches[0]
        await page.close()
        remaining=list(context.pages); session.page=remaining[-1] if remaining else None; self._page=session.page
        return BrowserActionResult(True,"close_tab","Closed browser tab.",
                                   await self.state() if session.page is not None else None,
                                   {"session_id":session.session_id,"remaining_tabs":len(remaining)})

    async def close_all_tabs(self) -> BrowserActionResult:
        session=self._require_active_session()
        if session.transport=="native":
            windows=browser_windows_by_executable(session.browser_name)
            if not windows and (session.native_hwnd or session.pid):
                windows=[(int(session.native_hwnd or 0),int(session.pid or 0))]
            closed=0
            for hwnd,pid in windows:
                session.native_hwnd=int(hwnd); session.pid=int(pid)
                if focus_native_session(session):
                    self._native_hotkey("ctrl","shift","w"); await asyncio.sleep(0.10); closed+=1
            session.native_hwnd=0
            return BrowserActionResult(True,"close_all_tabs",
                f"Closed all tabs across {closed} {session.browser_name.title()} window(s).",
                None,{"session_id":session.session_id,"windows_closed":closed})
        context=session.context
        if context is None: raise BrowserEngineError("The active session has no browser context.")
        for page in list(context.pages):
            try: await page.close()
            except Exception: pass
        session.page=None; self._page=None
        return BrowserActionResult(True,"close_all_tabs","Closed all tabs in the active browser session.",
                                   None,{"session_id":session.session_id,"remaining_tabs":0})


    async def back(self) -> BrowserActionResult:
        return await self._history_action("back")

    async def forward(self) -> BrowserActionResult:
        return await self._history_action("forward")

    async def reload(self) -> BrowserActionResult:
        session = self._require_active_session()
        if session.transport == "native":
            await self._native_focus_or_raise(session)
            self._native_hotkey("ctrl", "r")
            return BrowserActionResult(True, "reload", "Reloaded the active browser tab.", await self.state())
        page = self._require_page()
        await page.reload(wait_until="domcontentloaded")
        return BrowserActionResult(True, "reload", "Reloaded the active browser tab.", await self.state())

    async def screenshot(self, path: str = "") -> BrowserActionResult:
        session = self._require_active_session()
        destination = Path(path).expanduser().resolve() if path.strip() else (
            Path.cwd() / "screenshots" / f"browser-{int(time.time())}.png"
        ).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)

        if session.transport == "native":
            from PIL import ImageGrab
            await self._native_focus_or_raise(session)
            rect = native_window_rect(session)
            image = ImageGrab.grab(bbox=rect) if rect else ImageGrab.grab()
            image.save(destination)
        else:
            page = self._require_page()
            await page.screenshot(path=str(destination), full_page=False)
        return BrowserActionResult(
            True, "screenshot", f"Saved browser screenshot to {destination}.",
            await self.state(), {"path": str(destination), "session_id": session.session_id},
        )

    async def download_active(
        self,
        target: BrowserTarget,
        *,
        filename: str | None = None,
    ) -> BrowserActionResult:
        session = self._require_active_session()
        if session.transport == "native":
            raise BrowserEngineError(
                "Structured browser.download requires an automation-attached session. "
                "The real-profile browser can still download through normal visible UI."
            )
        result = await self.download(target, filename=filename)
        return BrowserActionResult(
            True, "download", f"Downloaded {result.suggested_filename}.",
            await self.state(),
            {"saved_path": str(result.saved_path), "url": result.url},
        )

    async def installed(self) -> BrowserActionResult:
        browsers = installed_browsers()
        default_name = ""
        try:
            default_name = default_browser_descriptor().name
        except Exception:
            pass
        return BrowserActionResult(
            True, "installed_browsers",
            f"Detected {len(browsers)} supported installed browser(s).",
            None,
            {"browsers": browsers, "default_browser": default_name},
        )

    async def _history_action(self, action: str) -> BrowserActionResult:
        session = self._require_active_session()
        if session.transport == "native":
            await self._native_focus_or_raise(session)
            self._native_hotkey("alt", "left" if action == "back" else "right")
            return BrowserActionResult(
                True, action, f"Browser {action} executed.", await self.state()
            )
        page = self._require_page()
        if action == "back":
            await page.go_back(wait_until="domcontentloaded")
        else:
            await page.go_forward(wait_until="domcontentloaded")
        return BrowserActionResult(True, action, f"Browser {action} executed.", await self.state())

    async def _ensure_playwright(self) -> None:
        if self._playwright is None:
            if async_playwright is None:
                raise BrowserEngineError("Playwright is not installed.")
            self._playwright = await async_playwright().start()

    def _next_session_id(self, browser_name: str) -> str:
        self._session_counter += 1
        slug = re.sub(r"[^a-z0-9]+", "-", browser_name.casefold()).strip("-") or "browser"
        return f"{slug}-{self._session_counter}"

    async def switch_browser(self, browser_name: str) -> BrowserActionResult:
        descriptor = resolve_descriptor(browser_name)
        matches = [
            item for item in self._sessions.values()
            if item.browser_name == descriptor.name
        ]
        if not matches:
            raise BrowserEngineError(
                f"There is no active Conduit session for {descriptor.name.title()}."
            )
        session = matches[-1]
        self._select_session(session)
        if session.transport == "native":
            await self._native_focus_or_raise(session)
        elif session.page is not None:
            await session.page.bring_to_front()
        return BrowserActionResult(
            True,
            "switch_session",
            f"Switched to {descriptor.name.title()} session {session.session_id}.",
            await self.state(),
            session.data(active=True),
        )

    def _native_read_current_url(self) -> str:
        """Read active native-browser URL while preserving the clipboard."""
        import sys
        if sys.platform != "win32":
            return ""

        import pyautogui
        root = None
        old_clipboard = None
        had_clipboard = False
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            try:
                old_clipboard = root.clipboard_get()
                had_clipboard = True
            except Exception:
                pass

            pyautogui.hotkey("ctrl", "l")
            time.sleep(0.03)
            pyautogui.hotkey("ctrl", "c")
            time.sleep(0.04)
            try:
                url = root.clipboard_get().strip()
            except Exception:
                url = ""
            pyautogui.press("esc")

            try:
                root.clipboard_clear()
                if had_clipboard and old_clipboard is not None:
                    root.clipboard_append(old_clipboard)
                root.update()
            except Exception:
                pass
            return url
        except Exception:
            try:
                pyautogui.press("esc")
            except Exception:
                pass
            return ""
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

    @staticmethod
    def _native_tab_matches(item: dict[str, object], wanted: str) -> bool:
        wanted_cf = wanted.casefold().strip()
        title = str(item.get("title", "")).casefold()
        url = str(item.get("url", "")).casefold()

        if wanted_cf in title or wanted_cf in url:
            return True

        aliases = {
            "gmail": ("mail.google.com", "gmail.com"),
            "youtube": ("youtube.com", "youtu.be"),
            "github": ("github.com",),
            "reddit": ("reddit.com",),
            "twitch": ("twitch.tv",),
            "google": ("google.com",),
            "facebook": ("facebook.com",),
            "instagram": ("instagram.com",),
            "whatsapp": ("web.whatsapp.com",),
        }
        return any(marker in url for marker in aliases.get(wanted_cf, ()))

    def _native_uia_tabs_for_window(
        self,
        session: BrowserSession,
        hwnd: int,
        pid: int,
    ) -> list[dict[str, object]]:
        """Read browser tab items through Windows UI Automation without changing tabs."""
        if os.name != "nt":
            return []
        try:
            from pywinauto import Desktop
        except Exception:
            return []

        try:
            window = Desktop(backend="uia").window(handle=int(hwnd))
            # UIA exposes Chromium/Opera/Firefox tab-strip items without requiring
            # Conduit to activate every tab or copy every URL.
            items = window.descendants(control_type="TabItem")
        except Exception:
            return []

        tabs: list[dict[str, object]] = []
        seen: set[tuple[str, str]] = set()
        order = 0
        for item in items:
            try:
                title = (item.window_text() or "").strip()
            except Exception:
                title = ""
            if not title:
                continue

            # Browser chrome can expose non-page TabItems in some builds. Keep
            # unique visible tab-strip items in the order UIA reports them.
            try:
                auto_id = (item.element_info.automation_id or "").strip()
            except Exception:
                auto_id = ""
            key = (title, auto_id)
            if key in seen:
                continue
            seen.add(key)
            order += 1

            try:
                selected = bool(item.is_selected())
            except Exception:
                selected = False

            tabs.append({
                "title": title,
                "url": "",
                "window_hwnd": int(hwnd),
                "window_pid": int(pid),
                "window_tab_order": order,
                "uia_item": item,
                "active": selected,
            })
        return tabs

    async def _native_collect_tabs_for_window(
        self,
        session: BrowserSession,
        hwnd: int,
        pid: int,
        *,
        max_tabs: int = 40,
    ) -> list[dict[str, object]]:
        """Inventory tabs left-to-right regardless of Opera GX Ctrl+Tab mode."""
        session.native_hwnd = int(hwnd)
        session.pid = int(pid)
        await self._native_focus_or_raise(session)

        original_title = native_window_title(session).strip()
        original_url = self._native_read_current_url()

        self._native_hotkey("ctrl", "1")
        await asyncio.sleep(0.10)

        first_title = native_window_title(session).strip()
        first_url = self._native_read_current_url()
        if not first_title and not first_url:
            return []

        tabs = [{
            "title": first_title,
            "url": first_url,
            "window_hwnd": int(hwnd),
            "window_pid": int(pid),
            "window_tab_order": 1,
        }]

        for order in range(2, max_tabs + 1):
            self._native_hotkey("ctrl", "pagedown")
            await asyncio.sleep(0.09)

            title = native_window_title(session).strip()
            url = self._native_read_current_url()

            same_title = title == first_title
            same_url = (not first_url and not url) or url == first_url
            if same_title and same_url:
                break

            tabs.append({
                "title": title,
                "url": url,
                "window_hwnd": int(hwnd),
                "window_pid": int(pid),
                "window_tab_order": order,
            })

        # Restore the tab that was active before scanning.
        if original_title or original_url:
            self._native_hotkey("ctrl", "1")
            await asyncio.sleep(0.07)
            for _ in range(max_tabs):
                title = native_window_title(session).strip()
                url = self._native_read_current_url()
                if (
                    (original_title and title == original_title)
                    or (original_url and url == original_url)
                ):
                    break
                self._native_hotkey("ctrl", "pagedown")
                await asyncio.sleep(0.06)

        return tabs

    async def _native_collect_all_tabs(
        self,
        session: BrowserSession,
    ) -> list[dict[str, object]]:
        windows = browser_windows_by_executable(session.browser_name)
        if not windows and (session.native_hwnd or session.pid):
            windows = [(int(session.native_hwnd or 0), int(session.pid or 0))]
        if not windows:
            return []

        all_tabs: list[dict[str, object]] = []
        for window_number, (hwnd, pid) in enumerate(windows, start=1):
            # Preferred path: Windows UI Automation. This inventories the tab
            # strip in the background without Ctrl+1/PageDown or URL copying.
            items = self._native_uia_tabs_for_window(session, hwnd, pid)

            # Compatibility fallback for browsers/builds that expose no TabItems.
            # This preserves the older implementation rather than breaking them.
            if not items:
                items = await self._native_collect_tabs_for_window(session, hwnd, pid)

            for item in items:
                item["window"] = window_number
                item.setdefault("active", False)
                all_tabs.append(item)

        for index, item in enumerate(all_tabs, start=1):
            item["index"] = index
        return all_tabs

    async def _native_activate_inventory_tab(
        self,
        session: BrowserSession,
        item: dict[str, object],
    ) -> None:
        session.native_hwnd = int(item["window_hwnd"])
        session.pid = int(item["window_pid"])
        await self._native_focus_or_raise(session)

        uia_item = item.get("uia_item")
        if uia_item is not None:
            try:
                # UIA SelectionItem.Select changes directly to the requested tab.
                # No Ctrl+1/PageDown traversal and no mouse movement is required.
                uia_item.select()
                await asyncio.sleep(0.08)
                return
            except Exception:
                pass

        # Compatibility fallback for a browser that could be inventoried only by
        # the older keyboard path.
        self._native_hotkey("ctrl", "1")
        await asyncio.sleep(0.08)
        for _ in range(int(item["window_tab_order"]) - 1):
            self._native_hotkey("ctrl", "pagedown")
            await asyncio.sleep(0.07)


    def _register_session(self, session: BrowserSession) -> BrowserSession:
        if session.transport == "native":
            for old_id, old in list(self._sessions.items()):
                if (
                    old.transport == "native"
                    and old.browser_name == session.browser_name
                    and bool(old.private) == bool(session.private)
                ):
                    # Reuse the original logical ID while refreshing the actual
                    # Windows process/window metadata from the latest open.
                    session.session_id = old.session_id
                    self._sessions.pop(old_id, None)
                    break
        self._sessions[session.session_id] = session
        return session

    def _active_session(self) -> BrowserSession | None:
        if self._active_session_id:
            return self._sessions.get(self._active_session_id)
        return None

    def _require_active_session(self) -> BrowserSession:
        session = self._active_session()
        if session is None:
            raise BrowserNotStartedError("No browser session is active.")
        return session

    def _select_session(self, session: BrowserSession) -> None:
        self._active_session_id = session.session_id
        self._browser = session.browser
        self._context = session.context
        self._page = session.page

    async def _native_focus_or_raise(self, session: BrowserSession) -> None:
        if not focus_native_session(session):
            # Browser startup may still be completing.
            await asyncio.sleep(0.35)
            if not focus_native_session(session):
                raise BrowserEngineError(
                    f"I couldn't safely focus the {session.browser_name.title()} window."
                )

    @staticmethod
    def _native_hotkey(*keys: str) -> None:
        import pyautogui
        pyautogui.hotkey(*keys)

    @staticmethod
    def _native_press(key: str) -> None:
        import pyautogui
        pyautogui.press(key)

    @staticmethod
    def _native_type(text: str) -> None:
        import pyautogui
        # Clipboard avoids slow per-character typing and handles punctuation/URLs.
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(text)
            root.update()
            root.destroy()
            pyautogui.hotkey("ctrl", "v")
        except Exception:
            pyautogui.write(text, interval=0.005)

    def _locator(self, target: BrowserTarget) -> Locator:
        page = self._require_page()
        if target.kind is TargetKind.ROLE:
            return page.get_by_role(target.value, name=target.name, exact=target.exact)
        if target.kind is TargetKind.TEXT:
            return page.get_by_text(target.value, exact=target.exact)
        if target.kind is TargetKind.LABEL:
            return page.get_by_label(target.value, exact=target.exact)
        if target.kind is TargetKind.PLACEHOLDER:
            return page.get_by_placeholder(target.value, exact=target.exact)
        if target.kind is TargetKind.TEST_ID:
            return page.get_by_test_id(target.value)
        if target.kind is TargetKind.CSS:
            return page.locator(target.value)
        raise BrowserTargetError(f"Unsupported target kind: {target.kind}")

    def _require_page(self) -> Page:
        if self._page is None:
            raise BrowserNotStartedError("Browser session has not been started.")
        return self._page

    async def _run_action(self, action: str, payload: dict[str, object], operation: Any, *, success_message: str) -> BrowserActionResult:
        await self._emit(EventNames.BROWSER_ACTION_STARTED, {"action": action, **payload})
        try:
            await operation
            result = BrowserActionResult(True, action, success_message, await self.state())
            await self._emit(EventNames.BROWSER_COMPLETED, self._result_payload(result))
            return result
        except Exception as exc:
            await self._emit(EventNames.BROWSER_FAILED, {"action": action, "error": str(exc), **payload})
            raise BrowserEngineError(f"Browser action '{action}' failed: {exc}") from exc

    async def _emit(self, name: str, payload: dict[str, object]) -> None:
        if self.events is not None:
            await self.events.emit(name, source="BrowserEngine", payload=payload)

    @staticmethod
    def _normalize_url(url: str) -> str:
        value = url.strip()
        if not value:
            raise ValueError("URL cannot be empty.")
        if "://" not in value and not value.startswith(("data:", "file:")):
            value = "https://" + value
        return value

    @staticmethod
    def _target_payload(target: BrowserTarget) -> dict[str, object]:
        return {"kind": target.kind.value, "value": target.value, "name": target.name, "exact": target.exact}

    @staticmethod
    def _result_payload(result: BrowserActionResult) -> dict[str, object]:
        return {"action": result.action, "success": result.success, "message": result.message, "url": result.state.url if result.state else None}
