"""Structured YouTube intelligence and playback helpers.

Discovery/info/transcript work is performed in the background. Any action whose
purpose is to show a video to the user hands the final YouTube URL to Windows,
which preserves Conduit's global visible-browser policy.
"""
from __future__ import annotations

import ctypes
import difflib
import difflib
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

_YOUTUBE_WATCH = "https://www.youtube.com/watch?v="
_PLAYBACK_STATE = "unknown"


@dataclass(frozen=True, slots=True)
class YouTubeVideo:
    video_id: str
    title: str
    url: str
    channel: str = ""
    duration: int | None = None
    view_count: int | None = None
    upload_date: str = ""
    description: str = ""

    def data(self) -> dict[str, Any]:
        return asdict(self)


def _ydl_options(*, flat: bool = False) -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist" if flat else False,
        "noplaylist": True,
        "socket_timeout": 15,
    }


def _video_from_entry(entry: dict[str, Any]) -> YouTubeVideo:
    video_id = str(entry.get("id") or "").strip()
    url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
    if video_id and (not url or not url.startswith("http")):
        url = _YOUTUBE_WATCH + video_id
    return YouTubeVideo(
        video_id=video_id,
        title=str(entry.get("title") or "YouTube video").strip(),
        url=url,
        channel=str(entry.get("channel") or entry.get("uploader") or "").strip(),
        duration=_int_or_none(entry.get("duration")),
        view_count=_int_or_none(entry.get("view_count")),
        upload_date=str(entry.get("upload_date") or "").strip(),
        description=str(entry.get("description") or "").strip(),
    )


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_video_reference(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("A YouTube video URL, video id, or search query is required.")
    match = re.search(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{6,})", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", value):
        return value
    return value


def search(query: str, *, limit: int = 5) -> list[YouTubeVideo]:
    from yt_dlp import YoutubeDL
    query = " ".join(query.split()).strip()
    if not query:
        raise ValueError("YouTube search query cannot be empty.")
    count = max(1, min(int(limit), 20))
    with YoutubeDL(_ydl_options(flat=True)) as ydl:
        payload = ydl.extract_info(f"ytsearch{count}:{query}", download=False) or {}
    return [
        _video_from_entry(item)
        for item in (payload.get("entries") or [])
        if isinstance(item, dict) and item.get("id")
    ][:count]


def matching_candidates(
    description: str,
    *,
    search_query: str = "",
    channel: str = "",
    limit: int = 8,
) -> list[YouTubeVideo]:
    """Search YouTube for a vaguely remembered video without opening a browser."""
    description = " ".join(description.split()).strip()
    query = " ".join((search_query or description).split()).strip()
    channel = " ".join(channel.split()).strip()
    if not query:
        raise ValueError("A remembered-video description or search query is required.")
    if channel and channel.casefold() not in query.casefold():
        query = f"{channel} {query}"
    return search(query, limit=max(3, min(int(limit), 12)))


def play_matching_visible(
    description: str,
    *,
    search_query: str = "",
    channel: str = "",
) -> YouTubeVideo:
    """Fallback matcher: trust YouTube's top semantic search result and open it."""
    global _PLAYBACK_STATE
    candidates = matching_candidates(
        description,
        search_query=search_query,
        channel=channel,
        limit=5,
    )
    if not candidates:
        raise RuntimeError("No matching YouTube video was found.")
    video = candidates[0]
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def resolve_video(value: str) -> YouTubeVideo:
    from yt_dlp import YoutubeDL
    ref = normalize_video_reference(value)
    if re.fullmatch(r"[A-Za-z0-9_-]{6,}", ref):
        target = _YOUTUBE_WATCH + ref
    elif ref.startswith(("http://", "https://")):
        target = ref
    else:
        found = search(ref, limit=1)
        if not found:
            raise RuntimeError(f"No YouTube video was found for {value!r}.")
        target = found[0].url
    with YoutubeDL(_ydl_options(flat=False)) as ydl:
        info = ydl.extract_info(target, download=False) or {}
    return _video_from_entry(info)


def get_info(value: str) -> YouTubeVideo:
    return resolve_video(value)


def get_transcript(value: str, *, languages: list[str] | None = None) -> dict[str, Any]:
    from youtube_transcript_api import YouTubeTranscriptApi
    video = resolve_video(value)
    langs = languages or ["en"]
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video.video_id, languages=langs)
        snippets = list(fetched)
        parts = [str(getattr(item, "text", "")).strip() for item in snippets]
        language = str(getattr(fetched, "language_code", "") or "")
    except AttributeError:
        # Compatibility with older youtube-transcript-api releases.
        rows = YouTubeTranscriptApi.get_transcript(video.video_id, languages=langs)
        parts = [str(item.get("text", "")).strip() for item in rows]
        language = langs[0] if langs else ""
    text = " ".join(part for part in parts if part)
    if not text:
        raise RuntimeError("No usable transcript was available for this video.")
    return {
        "video": video.data(),
        "language": language,
        "text": text,
        "characters": len(text),
    }


def trending(*, region: str = "US", limit: int = 10) -> list[YouTubeVideo]:
    """Return a best-effort structured trending feed without opening a browser."""
    from yt_dlp import YoutubeDL
    count = max(1, min(int(limit), 25))
    opts = _ydl_options(flat=True)
    opts["geo_bypass_country"] = (region or "US").upper()
    urls = (
        "https://www.youtube.com/feed/trending",
        "https://www.youtube.com/feed/explore",
    )
    for url in urls:
        try:
            with YoutubeDL(opts) as ydl:
                payload = ydl.extract_info(url, download=False) or {}
            items = [
                _video_from_entry(item)
                for item in (payload.get("entries") or [])
                if isinstance(item, dict) and item.get("id")
            ]
            if items:
                return items[:count]
        except Exception:
            continue
    # YouTube sometimes removes/changes the public Trending feed. Keep this
    # structured and background-only rather than opening a visible browser.
    return search(f"trending videos today {region}", limit=count)


def _norm_channel_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _resolve_channel_identity(channel: str) -> tuple[str, str, str]:
    """Resolve a human channel name/handle/URL to (channel_id, name, url).

    Never invent a YouTube handle from a display name. Handles may differ from
    display names (for example spaces, punctuation, aliases, or legacy names).
    """
    from yt_dlp import YoutubeDL

    value = " ".join(channel.split()).strip()
    if not value:
        raise ValueError("YouTube channel cannot be empty.")

    opts = _ydl_options(flat=True)

    # A real channel URL/handle URL may be resolved directly.
    if value.startswith(("http://", "https://")):
        target = value.rstrip("/")
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(target, download=False) or {}
        channel_id = str(info.get("channel_id") or info.get("id") or "").strip()
        name = str(info.get("channel") or info.get("uploader") or info.get("title") or value).strip()
        url = str(info.get("channel_url") or info.get("webpage_url") or target).strip()
        if channel_id:
            return channel_id, name, url

    # If the user supplied an explicit @handle, resolve that exact handle.
    if value.startswith("@") and " " not in value:
        target = f"https://www.youtube.com/{value}"
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=False) or {}
            channel_id = str(info.get("channel_id") or info.get("id") or "").strip()
            name = str(info.get("channel") or info.get("uploader") or info.get("title") or value).strip()
            url = str(info.get("channel_url") or info.get("webpage_url") or target).strip()
            if channel_id:
                return channel_id, name, url
        except Exception:
            pass

    # Human names are resolved through actual YouTube search results. Search
    # videos because their metadata reliably exposes channel_id/channel_url.
    with YoutubeDL(opts) as ydl:
        payload = ydl.extract_info(f"ytsearch12:{value}", download=False) or {}
    entries = [
        item for item in (payload.get("entries") or [])
        if isinstance(item, dict) and item.get("channel_id")
    ]
    if not entries:
        raise RuntimeError(f"No YouTube channel could be resolved for {channel!r}.")

    wanted = _norm_channel_name(value.lstrip("@"))
    def score(item: dict[str, Any]) -> tuple[int, int]:
        name = str(item.get("channel") or item.get("uploader") or "")
        cid = str(item.get("channel_id") or "")
        exact = int(_norm_channel_name(name) == wanted)
        # Frequency helps when several search results come from the same likely
        # channel. Exact display-name match remains strongest.
        frequency = sum(
            1 for other in entries
            if str(other.get("channel_id") or "") == cid
        )
        return exact, frequency

    best = max(entries, key=score)
    channel_id = str(best.get("channel_id") or "").strip()
    name = str(best.get("channel") or best.get("uploader") or value).strip()
    url = str(best.get("channel_url") or "").strip()
    if not url:
        url = f"https://www.youtube.com/channel/{channel_id}"
    return channel_id, name, url


def _latest_from_rss(channel_id: str) -> YouTubeVideo | None:
    """Read YouTube's chronological channel feed; newest entry is first."""
    import urllib.request
    import xml.etree.ElementTree as ET

    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(
        feed_url,
        headers={"User-Agent": "Mozilla/5.0 Conduit/2.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read()
        root = ET.fromstring(raw)
    except Exception:
        return None

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/",
    }
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None
    video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
    title = (entry.findtext("atom:title", default="YouTube video", namespaces=ns) or "").strip()
    author = entry.find("atom:author", ns)
    channel_name = ""
    if author is not None:
        channel_name = (author.findtext("atom:name", default="", namespaces=ns) or "").strip()
    published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
    upload_date = published[:10].replace("-", "") if published else ""
    if not video_id:
        return None
    return YouTubeVideo(
        video_id=video_id,
        title=title,
        url=_YOUTUBE_WATCH + video_id,
        channel=channel_name,
        upload_date=upload_date,
    )


def _video_from_channel_sort_chip(channel: str, sort_label: str) -> YouTubeVideo:
    """Use YouTube's real Videos-page sorting chip in a hidden browser.

    This intentionally mirrors the user-facing YouTube UI (Latest / Popular /
    Oldest) instead of guessing query parameters. The browser is headless, so
    nothing appears on the user's screen.
    """
    from playwright.sync_api import sync_playwright

    channel_id, channel_name, _ = _resolve_channel_identity(channel)
    url = f"https://www.youtube.com/channel/{channel_id}/videos"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="en-US")
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            page.wait_for_timeout(1_500)

            # Common YouTube consent dialogs. Failure to find one is normal.
            for name in ("Reject all", "Accept all", "I agree", "Accept"):
                try:
                    button = page.get_by_role("button", name=name, exact=True)
                    if button.count() and button.first.is_visible():
                        button.first.click(timeout=2_000)
                        page.wait_for_timeout(700)
                        break
                except Exception:
                    pass

            # YouTube currently renders Latest / Popular / Oldest as selectable
            # chips on the Videos page. Try semantic controls first, then text.
            clicked = False
            candidates = (
                page.get_by_role("tab", name=sort_label, exact=True),
                page.get_by_role("button", name=sort_label, exact=True),
                page.get_by_text(sort_label, exact=True),
            )
            for candidate in candidates:
                try:
                    if candidate.count() and candidate.first.is_visible():
                        candidate.first.click(timeout=4_000)
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                raise RuntimeError(
                    f"YouTube's {sort_label!r} sorting control was not available "
                    f"for {channel_name!r}."
                )

            # Give YouTube's client-side grid time to refresh after sorting.
            page.wait_for_timeout(1_500)

            selectors = (
                "ytd-rich-grid-renderer a[href^='/watch?v=']",
                "ytd-rich-item-renderer a[href^='/watch?v=']",
                "yt-lockup-view-model a[href^='/watch?v=']",
                "a#video-title-link[href^='/watch?v=']",
                "a#video-title[href^='/watch?v=']",
                "a#thumbnail[href^='/watch?v=']",
            )

            video_id = ""
            title = ""
            for selector in selectors:
                links = page.locator(selector)
                try:
                    count = min(links.count(), 20)
                except Exception:
                    continue
                seen: set[str] = set()
                for index in range(count):
                    link = links.nth(index)
                    try:
                        href = str(link.get_attribute("href") or "")
                        match = re.search(r"/watch\?v=([A-Za-z0-9_-]{6,})", href)
                        if not match:
                            continue
                        vid = match.group(1)
                        if vid in seen:
                            continue
                        seen.add(vid)
                        video_id = vid
                        title = " ".join(
                            str(
                                link.get_attribute("title")
                                or link.get_attribute("aria-label")
                                or link.inner_text()
                                or ""
                            ).split()
                        )
                        break
                    except Exception:
                        continue
                if video_id:
                    break

            if not video_id:
                raise RuntimeError(
                    f"YouTube's {sort_label!r} view loaded for {channel_name!r}, "
                    "but no normal video could be identified."
                )
        finally:
            browser.close()

    # Verify the selected video belongs to the exact resolved channel and enrich
    # its metadata. If detailed extraction is temporarily blocked, still return
    # the UI-selected video rather than substituting a different result.
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL(_ydl_options(flat=False)) as ydl:
            info = ydl.extract_info(_YOUTUBE_WATCH + video_id, download=False) or {}
        actual_channel_id = str(info.get("channel_id") or "").strip()
        if actual_channel_id and actual_channel_id != channel_id:
            raise RuntimeError(
                f"YouTube selected a video outside resolved channel {channel_name!r}."
            )
        return _video_from_entry(info)
    except RuntimeError:
        raise
    except Exception:
        return YouTubeVideo(
            video_id=video_id,
            title=title or f"{sort_label} upload",
            url=_YOUTUBE_WATCH + video_id,
            channel=channel_name,
        )


def latest_upload(channel: str) -> YouTubeVideo:
    """Return the first video in YouTube's actual Latest-sorted Videos view."""
    try:
        return _video_from_channel_sort_chip(channel, "Latest")
    except Exception:
        # Conservative fallback: canonical Videos tab is normally newest-first.
        # RSS remains a second fallback if YouTube's tab extraction is unavailable.
        from yt_dlp import YoutubeDL
        channel_id, channel_name, _ = _resolve_channel_identity(channel)
        opts = _ydl_options(flat=True)
        opts["playlistend"] = 5
        videos_url = f"https://www.youtube.com/channel/{channel_id}/videos"
        try:
            with YoutubeDL(opts) as ydl:
                payload = ydl.extract_info(videos_url, download=False) or {}
            entries = [
                item for item in (payload.get("entries") or [])
                if isinstance(item, dict) and item.get("id")
            ]
        except Exception:
            entries = []
        if entries:
            return _video_from_entry(entries[0])
        rss_video = _latest_from_rss(channel_id)
        if rss_video is not None:
            return rss_video
        raise RuntimeError(
            f"Resolved YouTube channel {channel_name!r}, but its latest video "
            "could not be retrieved."
        )


def _channel_video_entries(channel: str, *, limit: int | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Return videos from the exact resolved channel's normal Videos tab."""
    from yt_dlp import YoutubeDL

    channel_id, channel_name, _ = _resolve_channel_identity(channel)
    opts = _ydl_options(flat=True)
    if limit is not None:
        opts["playlistend"] = max(1, int(limit))
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    with YoutubeDL(opts) as ydl:
        payload = ydl.extract_info(url, download=False) or {}
    entries = [
        item for item in (payload.get("entries") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not entries:
        raise RuntimeError(f"No standard videos were retrieved for {channel_name!r}.")
    return channel_name, entries


def oldest_upload(channel: str) -> YouTubeVideo:
    """Return the first video in YouTube's actual Oldest-sorted Videos view."""
    try:
        return _video_from_channel_sort_chip(channel, "Oldest")
    except Exception:
        # Correctness-first fallback. Only use complete channel ordering; never
        # substitute a search result as "oldest".
        channel_name, entries = _channel_video_entries(channel, limit=None)
        if not entries:
            raise RuntimeError(f"No standard uploads were found for {channel_name!r}.")
        return _video_from_entry(entries[-1])


def play_oldest_upload_visible(channel: str) -> YouTubeVideo:
    global _PLAYBACK_STATE
    video = oldest_upload(channel)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def most_popular_upload(channel: str) -> YouTubeVideo:
    """Return the first video in YouTube's actual Popular-sorted Videos view.

    Correctness is preferred over guessing. If the Popular chip cannot be read,
    this raises an error instead of opening an arbitrary channel video.
    """
    return _video_from_channel_sort_chip(channel, "Popular")


def play_most_popular_visible(channel: str) -> YouTubeVideo:
    global _PLAYBACK_STATE
    video = most_popular_upload(channel)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def current_live_stream(channel: str) -> YouTubeVideo:
    """Return a currently-live stream from the exact resolved channel only."""
    from yt_dlp import YoutubeDL

    channel_id, channel_name, _ = _resolve_channel_identity(channel)
    live_url = f"https://www.youtube.com/channel/{channel_id}/live"
    opts = _ydl_options(flat=False)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(live_url, download=False) or {}
    except Exception as exc:
        raise RuntimeError(f"{channel_name} does not appear to be live on YouTube right now.") from exc

    item = _video_from_entry(info)
    actual_channel_id = str(info.get("channel_id") or "").strip()
    live_status = str(info.get("live_status") or "").casefold()
    is_live = bool(info.get("is_live")) or live_status == "is_live"

    if actual_channel_id != channel_id or not is_live:
        raise RuntimeError(f"{channel_name} does not appear to be live on YouTube right now.")
    return item


def play_live_visible(channel: str) -> YouTubeVideo:
    global _PLAYBACK_STATE
    video = current_live_stream(channel)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def play_latest_upload_visible(channel: str) -> YouTubeVideo:
    global _PLAYBACK_STATE
    video = latest_upload(channel)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video



_LATEST_MATCH_STOPWORDS = {
    "latest", "newest", "recent", "episode", "episodes", "drama", "serial",
    "show", "video", "videos", "youtube", "play", "open", "watch", "from",
    "channel", "official", "full", "today", "the", "a", "an", "of", "on",
    "and", "please",
}


def _latest_match_terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+", query.casefold())
    terms = [word for word in words if len(word) >= 3 and word not in _LATEST_MATCH_STOPWORDS]
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(terms))


def _normalized_words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _term_matches_haystack(term: str, haystack: str) -> bool:
    """Typo-tolerant token match for natural YouTube titles.

    This intentionally handles small spelling variations such as Zanjerein /
    Zanjeerain without turning unrelated words into matches.
    """
    if term in haystack:
        return True
    words = _normalized_words(haystack)
    for word in words:
        if abs(len(word) - len(term)) > 2:
            continue
        if difflib.SequenceMatcher(None, term, word).ratio() >= 0.84:
            return True
    return False


def _entry_relevance(entry: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 1
    title = str(entry.get("title") or "")
    description = str(entry.get("description") or "")
    channel = str(entry.get("channel") or entry.get("uploader") or "")
    title_cf = title.casefold()
    all_text = f"{title} {description} {channel}".casefold()

    score = 0
    for term in terms:
        if _term_matches_haystack(term, title_cf):
            score += 4
        elif _term_matches_haystack(term, all_text):
            score += 1
    return score


def _looks_like_full_episode(info: dict[str, Any]) -> bool:
    """Return True when metadata looks like a real numbered episode upload."""
    title = str(info.get("title") or "").casefold()
    numbered = bool(
        re.search(r"\bepisode\s*[-:#]?\s*\d+\b", title)
        or re.search(r"\bep\s*[-:#]?\s*\d+\b", title)
    )
    if not numbered:
        return False
    if any(bad in title for bad in (
        "review", "reaction", "promo", "teaser", "trailer", "prediction",
        "explained", "analysis", "ost", "song", "behind the scenes",
        "best scene", "clip", "shorts",
    )):
        return False
    duration = _int_or_none(info.get("duration"))
    if duration is not None and duration < 8 * 60:
        return False
    return True


def _episode_content_score(info: dict[str, Any], *, episode_intent: bool) -> int:
    """Prefer actual full episode uploads over clips/reviews/promos."""
    if not episode_intent:
        return 0
    title = str(info.get("title") or "").casefold()
    if _looks_like_full_episode(info):
        return 20
    score = 0
    if "episode" in title or re.search(r"\bep\s*\d+\b", title):
        score += 4
    if any(bad in title for bad in (
        "review", "reaction", "promo", "teaser", "trailer", "prediction",
        "explained", "analysis", "ost", "song", "behind the scenes",
        "best scene", "clip", "shorts",
    )):
        score -= 15
    return score


def _published_sort_value(info: dict[str, Any]) -> float:
    for key in ("timestamp", "release_timestamp"):
        value = info.get(key)
        try:
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            pass
    raw = str(info.get("upload_date") or "").strip()
    if re.fullmatch(r"\d{8}", raw):
        try:
            dt = datetime.strptime(raw, "%Y%m%d").replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
    return 0.0


def _enrich_video_entries(entries: list[dict[str, Any]], *, limit: int = 10) -> list[tuple[dict[str, Any], YouTubeVideo, float]]:
    """Fetch precise metadata for a bounded candidate list."""
    from yt_dlp import YoutubeDL

    enriched: list[tuple[dict[str, Any], YouTubeVideo, float]] = []
    opts = _ydl_options(flat=False)
    with YoutubeDL(opts) as ydl:
        for entry in entries[: max(1, min(int(limit), 24))]:
            video_id = str(entry.get("id") or "").strip()
            url = str(entry.get("webpage_url") or entry.get("url") or "").strip()
            if video_id and (not url or not url.startswith("http")):
                url = _YOUTUBE_WATCH + video_id
            if not url:
                continue
            try:
                info = ydl.extract_info(url, download=False) or {}
            except Exception:
                # Keep usable search metadata if enrichment of one candidate fails.
                info = dict(entry)
                info.setdefault("webpage_url", url)
            enriched.append((info, _video_from_entry(info), _published_sort_value(info)))
    return enriched


def latest_matching_video(query: str, *, channel: str = "", limit: int = 12) -> YouTubeVideo:
    """Resolve the newest relevant YouTube video for a topic/episode request.

    Search-result ranking is used only to discover candidates. Candidate relevance,
    content type, upload recency, and exact channel identity (when requested) are
    verified from enriched metadata before playback.
    """
    query = " ".join(query.split()).strip()
    channel = " ".join(channel.split()).strip()
    if not query:
        raise ValueError("A YouTube topic or episode query is required.")

    terms = _latest_match_terms(query)
    lowered_query = query.casefold()
    episode_intent = any(word in lowered_query for word in ("episode", "drama", "serial", "show"))

    if channel:
        # Resolve the exact requested channel first. Then use YouTube search to
        # discover the requested episode and verify every candidate against that
        # exact resolved channel_id. This is more reliable for TV networks than
        # scanning only the newest slice of their Videos feed, where many clips
        # can push the full episode out of view.
        from yt_dlp import YoutubeDL

        channel_id, channel_name, _ = _resolve_channel_identity(channel)
        count = max(12, min(int(limit) * 2, 20))
        scoped_query = f"{query} {channel_name}".strip()

        opts = _ydl_options(flat=True)
        with YoutubeDL(opts) as ydl:
            payload = ydl.extract_info(
                f"ytsearch{count}:{scoped_query}",
                download=False,
            ) or {}

        raw_entries = [
            dict(item) for item in (payload.get("entries") or [])
            if isinstance(item, dict) and item.get("id")
        ]
        if not raw_entries:
            raise RuntimeError(
                f"YouTube returned no results for {query!r} from {channel_name!r}."
            )

        enriched = _enrich_video_entries(
            raw_entries,
            limit=min(20, len(raw_entries)),
        )

        exact_relevant: list[tuple[int, float, int, YouTubeVideo, dict[str, Any]]] = []
        for rank, (info, video, stamp) in enumerate(enriched):
            actual_id = str(info.get("channel_id") or "").strip()
            # For an explicit channel request, channel identity is mandatory.
            # Missing or different IDs are rejected.
            if actual_id != channel_id:
                continue

            relevance = _entry_relevance(info, terms)
            if terms and relevance <= 0:
                continue

            if episode_intent and not _looks_like_full_episode(info):
                continue

            quality = relevance + _episode_content_score(
                info,
                episode_intent=episode_intent,
            )
            exact_relevant.append((quality, stamp, -rank, video, info))

        if not exact_relevant:
            # Correctness-first fallback: search may omit the desired full
            # episode even when it exists on the channel. Inspect a deeper slice
            # of the exact channel's own Videos feed, but still require a true
            # numbered full episode and exact channel identity when available.
            try:
                _, channel_entries = _channel_video_entries(
                    channel,
                    limit=max(100, min(int(limit) * 10, 160)),
                )
                preselected = []
                for entry in channel_entries:
                    title = str(entry.get("title") or "").casefold()
                    relevance = _entry_relevance(entry, terms)
                    if terms and relevance <= 0:
                        continue
                    if episode_intent and not (
                        re.search(r"\bepisode\s*[-:#]?\s*\d+\b", title)
                        or re.search(r"\bep\s*[-:#]?\s*\d+\b", title)
                    ):
                        continue
                    preselected.append(dict(entry))
                    if len(preselected) >= 20:
                        break

                fallback_enriched = _enrich_video_entries(
                    preselected,
                    limit=min(20, len(preselected)),
                ) if preselected else []

                for rank, (info, video, stamp) in enumerate(fallback_enriched):
                    actual_id = str(info.get("channel_id") or "").strip()
                    if actual_id and actual_id != channel_id:
                        continue
                    relevance = _entry_relevance(info, terms)
                    if terms and relevance <= 0:
                        continue
                    if episode_intent and not _looks_like_full_episode(info):
                        continue
                    quality = relevance + _episode_content_score(
                        info,
                        episode_intent=episode_intent,
                    )
                    exact_relevant.append((quality, stamp, -rank, video, info))
            except Exception:
                pass

        if not exact_relevant:
            raise RuntimeError(
                f"I resolved YouTube channel {channel_name!r}, but I couldn't find "
                f"a verified full episode from that exact channel matching {query!r}."
            )

        # Among true full episodes from the exact requested channel, choose the
        # newest upload. Relevance remains a guardrail, not a reason for a newer
        # clip to beat a real episode.
        best_quality = max(row[0] for row in exact_relevant)
        acceptable = [
            row for row in exact_relevant
            if row[0] >= best_quality - 2
        ]
        acceptable.sort(key=lambda row: (row[1], row[2]), reverse=True)
        return acceptable[0][3]

    from yt_dlp import YoutubeDL

    count = max(8, min(int(limit), 20))
    # Keep "episode" in the actual YouTube search query because it materially
    # improves result type, even though generic words are excluded from subject
    # token matching.
    opts = _ydl_options(flat=True)
    with YoutubeDL(opts) as ydl:
        payload = ydl.extract_info(f"ytsearch{count}:{query}", download=False) or {}
    raw_entries = [
        dict(item) for item in (payload.get("entries") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not raw_entries:
        raise RuntimeError(f"No YouTube results were found for {query!r}.")

    # Critical v2.0.60 change: flat yt-dlp search entries can omit title/channel
    # fields. Enrich BEFORE relevance scoring rather than rejecting empty metadata.
    enriched = _enrich_video_entries(raw_entries, limit=min(12, len(raw_entries)))
    scored: list[tuple[int, float, int, YouTubeVideo]] = []
    for rank, (info, video, stamp) in enumerate(enriched):
        relevance = _entry_relevance(info, terms)
        if terms and relevance <= 0:
            continue
        content_score = _episode_content_score(info, episode_intent=episode_intent)
        # YouTube ranking is only a weak tiebreaker, not the freshness authority.
        scored.append((relevance + content_score, stamp, -rank, video))

    if not scored:
        raise RuntimeError(
            f"YouTube returned results for {query!r}, but none remained relevant "
            "after reading their full metadata."
        )

    best_quality = max(row[0] for row in scored)
    acceptable = [row for row in scored if row[0] >= best_quality - 2]
    acceptable.sort(key=lambda row: (row[1], row[2]), reverse=True)
    return acceptable[0][3]


def play_latest_matching_visible(query: str, *, channel: str = "") -> YouTubeVideo:
    """Resolve and visibly play the newest relevant matching upload."""
    global _PLAYBACK_STATE
    video = latest_matching_video(query, channel=channel)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def open_visible(value: str) -> YouTubeVideo:
    global _PLAYBACK_STATE
    video = resolve_video(value)
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube playback currently targets Windows.")
    os.startfile(video.url)  # type: ignore[attr-defined]
    _PLAYBACK_STATE = "playing"
    return video


def open_search_visible(query: str) -> str:
    from urllib.parse import quote_plus
    if sys.platform != "win32":
        raise RuntimeError("Visible YouTube browsing currently targets Windows.")
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query.strip())
    os.startfile(url)  # type: ignore[attr-defined]
    return url


def pause() -> str:
    global _PLAYBACK_STATE
    if _PLAYBACK_STATE == "paused":
        return "paused"
    _send_media_play_pause()
    _PLAYBACK_STATE = "paused"
    return _PLAYBACK_STATE


def resume() -> str:
    global _PLAYBACK_STATE
    if _PLAYBACK_STATE == "playing":
        return "playing"
    _send_media_play_pause()
    _PLAYBACK_STATE = "playing"
    return _PLAYBACK_STATE


def _send_media_play_pause() -> None:
    if sys.platform != "win32":
        raise RuntimeError("YouTube playback control currently targets Windows.")
    # VK_MEDIA_PLAY_PAUSE = 0xB3. This controls the active Windows media session
    # without needing Chrome/Edge/Opera-specific automation.
    user32 = ctypes.windll.user32
    key = 0xB3
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, 2, 0)
