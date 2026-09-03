from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from conduit.core.models import ChatMessage, Role


@dataclass(frozen=True, slots=True)
class YouTubePlan:
    action: str
    arguments: dict[str, Any]
    needs_synthesis: bool = False


_ALLOWED = (
    "youtube.search",
    "youtube.play",
    "youtube.play_latest_upload",
    "youtube.play_oldest_upload",
    "youtube.play_most_popular",
    "youtube.play_live",
    "youtube.play_matching_video",
    "youtube.play_latest_matching",
    "youtube.get_info",
    "youtube.get_transcript",
    "youtube.summarize",
    "youtube.trending",
    "youtube.pause",
    "youtube.resume",
)


class AIYouTubeRouter:
    def __init__(self, provider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(self, user_message: str, *, recent_context: str = "") -> YouTubePlan | None:
        context = (
            "\nRECENT CONTEXT (only resolve references such as 'that video' or 'resume it'):\n"
            + recent_context
            if recent_context.strip()
            else ""
        )
        prompt = f"""You are Conduit's YOUTUBE ACTION ROUTER.
Decide whether the CURRENT request is a YouTube task. Correct typos mentally.
Do not answer the user.

AVAILABLE ACTIONS:
- youtube.search: background YouTube search; args query, optional limit
- youtube.play: find URL/id/query and visibly play in Windows DEFAULT browser; args video
- youtube.play_latest_upload: visibly play latest upload from a channel in DEFAULT browser; args channel
- youtube.play_oldest_upload: visibly play oldest normal upload from a channel in DEFAULT browser; args channel
- youtube.play_most_popular: verify and play the channel's highest-view-count normal upload; args channel
- youtube.play_live: verify and play the exact channel's CURRENT live stream only; args channel
- youtube.play_matching_video: user remembers/describes a video but does not know its exact title; args description, search_query, optional channel
- youtube.play_latest_matching: play the NEWEST relevant video/episode matching a topic/search phrase; args query, optional channel. If channel is present, only that exact channel may be considered.
- youtube.get_info: background metadata; args video
- youtube.get_transcript: background transcript; args video, optional languages
- youtube.summarize: background transcript retrieval for AI summarization; args video, optional languages
- youtube.trending: background trending discovery; args optional region, limit
- youtube.pause: pause current YouTube/media playback; no args
- youtube.resume: resume current YouTube/media playback; no args

POLICY:
Visible playback MUST use a dedicated youtube.play* action. NEVER choose browser.start,
browser.goto, browser.click, or any managed-browser action for visible YouTube playback.
Search/info/transcript/summarize/trending are background tasks and must not open a visible browser.
If this is not a YouTube task, return null.
For 'play X video', put the user's natural search phrase or URL in video.
Treat "yt" as YouTube.
For latest/newest upload FROM A CHANNEL with no topic constraint, choose youtube.play_latest_upload.
For requests like "play the latest episode of X", "play the newest X episode/video", or
"search X and play the latest one", choose youtube.play_latest_matching. Put the concise
topic/episode keywords in query. If the user explicitly names a channel (for example
"latest episode of X from channel ARY Digital"), include that exact user-supplied channel
in channel; never invent a channel.
For oldest/first upload, choose youtube.play_oldest_upload.
For most popular/most viewed upload FROM A CHANNEL, choose youtube.play_most_popular.
For a current livestream/live stream FROM A CHANNEL, choose youtube.play_live. Never use regular youtube.play for that.
When the user DESCRIBES a remembered video ("I saw a video where...", "find the video where...",
"there was a video in which...", etc.) and the exact title is unknown, choose youtube.play_matching_video.
For youtube.play_matching_video:
- description = preserve the user's meaningful remembered details.
- search_query = rewrite those details into a concise YouTube-style search query with likely subject/channel keywords.
- channel = include only when the user actually names a creator/channel; otherwise omit it.
Do NOT invent a channel that the user did not mention.
For channel-scoped actions, put only the human channel name/handle/URL in channel.

Return ONLY JSON or null:
{{"action":"youtube.play","arguments":{{"video":"..."}},"needs_synthesis":false}}
{context}

CURRENT REQUEST:
{user_message}
"""
        response = await self.provider.chat([ChatMessage(Role.USER, prompt)], model=self.model)
        raw_text = response.text.strip()
        if raw_text.casefold() in {"null", "none", ""}:
            return None
        raw = _parse(raw_text)
        action = str(raw.get("action", "")).strip()
        if action not in _ALLOWED:
            return None
        args = raw.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        return YouTubePlan(
            action=action,
            arguments=dict(args),
            needs_synthesis=bool(raw.get("needs_synthesis", action in {
                "youtube.search", "youtube.get_info", "youtube.get_transcript",
                "youtube.summarize", "youtube.trending",
            })),
        )


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
            raise ValueError("YouTube router returned invalid output.")
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("YouTube router must return an object or null.")
    return value
