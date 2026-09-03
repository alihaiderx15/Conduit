
from __future__ import annotations

LONG_ANSWER_NOTICE = (
    "The generated answer is too long to read aloud. "
    "You can read the full answer in the chat interface."
)


def speech_text_for_answer(answer: str, *, max_words: int = 50) -> str:
    """Return what the future TTS layer should speak for a chat answer."""
    clean = " ".join(str(answer or "").split())
    if not clean:
        return ""
    if len(clean.split()) > max_words:
        return LONG_ANSWER_NOTICE
    return clean
