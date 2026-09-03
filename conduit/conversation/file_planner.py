
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from conduit.core.models import ChatMessage, Role


@dataclass(frozen=True, slots=True)
class FilePlan:
    action: str
    path: str
    parameters: dict[str, Any]


_ALLOWED = {
    "inspect", "describe", "ocr", "resize", "compress", "convert",
    "extract_text", "summarize", "analyze", "to_word",
    "fix", "reformat", "translate", "word_count", "bullet_points",
    "statistics", "filter", "sort", "validate", "format", "convert_csv",
    "transcribe", "trim", "extract_audio", "extract_frame",
    "list", "extract",
}


class AIFileRouter:
    """Translate natural language into a constrained file-processing plan."""

    def __init__(self, provider, model: str) -> None:
        self.provider = provider
        self.model = model

    async def plan(self, message: str, *, active_file: str = "") -> FilePlan | None:
        prompt = f"""You are Conduit's FILE PROCESSING ROUTER.
Map the user's CURRENT request to one file-processing action.
Do not answer the user and do not invent shell commands.

SUPPORTED ACTIONS:
inspect, describe, ocr, resize, compress, convert,
extract_text, summarize, analyze, to_word,
fix, reformat, translate, word_count, bullet_points,
statistics, filter, sort, validate, format, convert_csv,
transcribe, trim, extract_audio, extract_frame, list, extract.

PARAMETER EXAMPLES:
resize -> {{"width":1920,"height":1080,"keep_aspect":true}}
compress image -> {{"quality":80}}
compress video -> {{"crf":28}}
convert -> {{"format":"png"}} / {{"format":"xlsx"}} / {{"format":"mp3"}}
translate -> {{"language":"Urdu"}}
summarize -> {{"save_file":false}} by default.
If the user explicitly asks to save/create/generate/export a summary file,
use {{"save_file":true}}.
filter -> {{"column":"Marks","operator":"gt","value":80}}
sort -> {{"column":"Name","ascending":true}}
trim -> {{"start":"00:00:10","end":"00:00:30"}}
extract_audio -> {{"format":"mp3"}}
extract_frame -> {{"time":"00:01:20","format":"jpg"}}
extract archive -> {{"destination":"C:\\\\path\\\\folder"}}

PATH RULES:
- If CURRENT ACTIVE FILE is not "(none)" and the user does NOT explicitly type
  an absolute file path, path MUST be "".
- NEVER put the user's instruction/sentence into the path field.
- "convert the pic into 1920x1080" with an active image means resize with
  width=1920, height=1080, keep_aspect=false.
- "convert this MP4/video to MP3" means extract_audio with format="mp3".
- "make this video an MP3" means extract_audio with format="mp3".
- If the user explicitly supplies a Windows path such as C:\\folder\\file.pdf,
  preserve it exactly.
- For a normal summary request, use save_file=false.
- Only use save_file=true when the user explicitly asks for a summary file or
  asks to save/create/generate/export the summary.
- If the request is not clearly file processing, return null.

CURRENT ACTIVE FILE:
{active_file or "(none)"}

Return ONLY JSON or null:
{{"action":"resize","path":"","parameters":{{"width":1920,"height":1080}}}}

USER REQUEST:
{message}
"""
        response = await self.provider.specialist_chat(
            [ChatMessage(Role.USER, prompt)],
            model=self.model,
        )
        raw = response.text.strip()
        if raw.casefold() in {"", "null", "none"}:
            return None
        value = _parse(raw)
        action = re.sub(
            r"[\\s-]+", "_", str(value.get("action", "")).casefold().strip()
        )
        path = str(value.get("path", "") or "").strip()
        params = value.get("parameters", {})
        if not isinstance(params, dict):
            params = {}
        params = dict(params)

        aliases = {
            "convert_to_mp3": ("extract_audio", {"format": "mp3"}),
            "convert_mp4_to_mp3": ("extract_audio", {"format": "mp3"}),
            "extract_audio_to_mp3": ("extract_audio", {"format": "mp3"}),
            "convert_to_word": ("to_word", {}),
            "pdf_to_word": ("to_word", {}),
            "count_words": ("word_count", {}),
            "list_contents": ("list", {}),
            "unzip": ("extract", {}),
        }
        if action in aliases:
            action, defaults = aliases[action]
            for key, val in defaults.items():
                params.setdefault(key, val)

        convert_match = re.fullmatch(r"convert_to_([a-z0-9]+)", action)
        if convert_match:
            fmt = convert_match.group(1)
            if fmt in {"mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "wma"}:
                action = "extract_audio"
            else:
                action = "convert"
            params.setdefault("format", fmt)

        if action not in _ALLOWED:
            return None

        # With a GUI-dropped active file, natural language must never become a
        # fake relative file path. Only preserve an explicit path-looking value.
        if active_file and path:
            explicit_path = bool(
                re.match(r"^[A-Za-z]:[\\\\/]", path)
                or path.startswith("\\\\")
                or path.startswith("/")
            )
            if not explicit_path:
                path = ""

        return FilePlan(action, path, params)


def _parse(text: str) -> dict[str, Any]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.I)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        obj = json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, flags=re.S)
        if not match:
            raise ValueError("File router returned invalid output.")
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError("File router output must be an object.")
    return obj
