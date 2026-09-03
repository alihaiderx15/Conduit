"""YouTube browser capability.

YouTube regularly changes its rendered component names.  This module therefore
avoids depending on one private custom-element selector.  It discovers normal
watch links using several DOM strategies, validates the candidates, and opens
the first usable upload from the channel's Videos tab.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urljoin, urlparse, parse_qs

from conduit.browser import BrowserEngine
from conduit.events import EventBus


@dataclass(frozen=True, slots=True)
class YouTubePlaybackResult:
    """Result of opening a channel's newest standard upload."""

    channel: str
    video_title: str
    video_url: str
    verified: bool


@dataclass(frozen=True, slots=True)
class _VideoCandidate:
    """A normalized video link discovered on the channel page."""

    href: str
    title: str


class YouTubeAgent:
    """Perform resilient YouTube channel actions with Playwright."""

    # These deliberately include both older Polymer and newer view-model layouts.
    _WATCH_LINK_SELECTORS = (
        "ytd-rich-grid-renderer a[href^='/watch?v=']",
        "ytd-rich-item-renderer a[href^='/watch?v=']",
        "yt-lockup-view-model a[href^='/watch?v=']",
        "a#thumbnail[href^='/watch?v=']",
        "a#video-title-link[href^='/watch?v=']",
        "a#video-title[href^='/watch?v=']",
        "a[href^='/watch?v=']",
        "a[href*='youtube.com/watch?v=']",
    )

    def __init__(self, browser: BrowserEngine, *, event_bus: EventBus | None = None) -> None:
        self.browser = browser
        self.events = event_bus

    async def play_latest_upload(self, channel: str) -> YouTubePlaybackResult:
        """Resolve the latest upload in the background, then open it in the
        Windows default browser. Never launch Playwright for visible playback.
        """
        import asyncio
        import os
        import sys
        from yt_dlp import YoutubeDL

        handle = self._normalize_handle(channel)

        def resolve() -> tuple[str, str]:
            url = f"https://www.youtube.com/{quote(handle, safe='@')}/videos"
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": "in_playlist",
                "playlistend": 1,
                "socket_timeout": 15,
            }
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False) or {}
            entries = [x for x in (info.get("entries") or []) if isinstance(x, dict)]
            if not entries:
                raise RuntimeError(f"No standard uploads were found for {handle!r}.")
            item = entries[0]
            vid = str(item.get("id") or "").strip()
            href = str(item.get("url") or "").strip()
            if vid and not href.startswith("http"):
                href = f"https://www.youtube.com/watch?v={vid}"
            title = str(item.get("title") or "Latest upload").strip()
            return title, href

        video_title, video_url = await asyncio.to_thread(resolve)
        if sys.platform != "win32":
            raise RuntimeError("Visible YouTube playback currently targets Windows.")
        os.startfile(video_url)  # type: ignore[attr-defined]
        return YouTubePlaybackResult(
            channel=handle,
            video_title=video_title,
            video_url=video_url,
            verified=self._is_watch_url(video_url),
        )

    async def _ensure_videos_tab(self, handle: str) -> None:
        """Open the channel Videos tab if YouTube redirected to the channel root."""
        page = self.browser.page
        if "/videos" in urlparse(page.url).path:
            return

        selectors = (
            f"a[href='/{handle}/videos']",
            f"a[href*='/{handle}/videos']",
            "a[role='tab'][href$='/videos']",
        )
        for selector in selectors:
            locator = page.locator(selector)
            try:
                if await locator.count() > 0:
                    await locator.first.click(timeout=4_000)
                    await page.wait_for_timeout(1_200)
                    return
            except Exception:
                continue

        # Final deterministic fallback.
        await page.goto(
            f"https://www.youtube.com/{quote(handle, safe='@')}/videos",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(1_200)

    async def _discover_video_candidates(self) -> list[_VideoCandidate]:
        """Return deduplicated watch links in current DOM order."""
        page = self.browser.page
        raw_items: list[dict[str, Any]] = []

        for selector in self._WATCH_LINK_SELECTORS:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            if count == 0:
                continue

            # Limit extraction to avoid processing menus, recommendations, or very
            # large hydrated DOMs. Channel pages place newest uploads first.
            for index in range(min(count, 80)):
                link = locator.nth(index)
                try:
                    href = await link.get_attribute("href")
                    title = (
                        await link.get_attribute("title")
                        or await link.get_attribute("aria-label")
                        or (await link.inner_text())
                        or ""
                    )
                    raw_items.append({"href": href or "", "title": title.strip()})
                except Exception:
                    continue

            if raw_items:
                # The first selector that yields valid channel video links is
                # usually the most specific and preserves newest-first order.
                normalized = self._normalize_candidates(raw_items)
                if normalized:
                    return normalized

        # Last-resort extraction through the browser DOM, useful when custom
        # elements changed but anchors are still present.
        try:
            raw_items = await page.eval_on_selector_all(
                "a[href]",
                """els => els.map(a => ({
                    href: a.getAttribute('href') || '',
                    title: a.getAttribute('title') || a.getAttribute('aria-label') || a.textContent || ''
                }))""",
            )
        except Exception:
            raw_items = []
        return self._normalize_candidates(raw_items)

    @classmethod
    def _normalize_candidates(cls, items: list[dict[str, Any]]) -> list[_VideoCandidate]:
        """Filter and deduplicate raw anchors while preserving page order."""
        candidates: list[_VideoCandidate] = []
        seen_ids: set[str] = set()

        for item in items:
            href = str(item.get("href", "")).strip()
            if not cls._is_watch_url(href):
                continue
            video_id = cls._video_id(href)
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            title = " ".join(str(item.get("title", "")).split())
            candidates.append(_VideoCandidate(href=href, title=title or "Latest upload"))

        return candidates

    async def _dismiss_consent_if_present(self) -> None:
        page = self.browser.page
        button_names = (
            "Accept all",
            "I agree",
            "Reject all",
            "Accept",
            "Agree",
        )
        for name in button_names:
            candidates = (
                page.get_by_role("button", name=name, exact=True),
                page.get_by_text(name, exact=True),
            )
            for candidate in candidates:
                try:
                    if await candidate.count() and await candidate.first.is_visible():
                        await candidate.first.click(timeout=2_000)
                        await page.wait_for_timeout(600)
                        return
                except Exception:
                    continue

    @staticmethod
    def _video_id(url: str) -> str | None:
        parsed = urlparse(urljoin("https://www.youtube.com", url))
        if parsed.path != "/watch":
            return None
        values = parse_qs(parsed.query).get("v", [])
        return values[0] if values and values[0] else None

    @classmethod
    def _is_watch_url(cls, url: str) -> bool:
        return cls._video_id(url) is not None

    @staticmethod
    def _normalize_handle(channel: str) -> str:
        value = channel.strip()
        if not value:
            raise ValueError("YouTube channel cannot be empty.")
        if value.startswith("https://www.youtube.com/"):
            value = value.rstrip("/").split("/")[-1]
        if not value.startswith("@"):
            value = "@" + value
        return value
