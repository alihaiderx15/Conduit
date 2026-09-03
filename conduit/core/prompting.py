"""Load and inject Conduit's provider-neutral core identity prompt."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

from conduit.core.models import ChatMessage, Role

_CORE_PROMPT_SENTINEL = "CONDUIT CORE PROTOCOL"


@lru_cache(maxsize=1)
def load_core_prompt() -> str:
    """Load Conduit's single packaged core prompt."""
    packaged_prompt = Path(__file__).resolve().with_name("prompt.txt")
    try:
        text = packaged_prompt.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        return text
    # Never break the assistant just because a deployment omitted the text file.
    return (
        "CONDUIT CORE PROTOCOL\n"
        "You are Conduit, a fast, professional desktop AI copilot developed by Ali Haider. "
        "Answer naturally and follow task-specific system instructions exactly."
    )


def with_core_prompt(messages: Sequence[ChatMessage]) -> tuple[ChatMessage, ...]:
    """Prepend Conduit's core prompt once to any provider chat request."""
    existing = tuple(messages)
    if any(
        message.role is Role.SYSTEM and _CORE_PROMPT_SENTINEL in message.content
        for message in existing
    ):
        return existing
    return (ChatMessage(Role.SYSTEM, load_core_prompt()), *existing)
