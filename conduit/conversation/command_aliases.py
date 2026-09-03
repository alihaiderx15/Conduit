
from __future__ import annotations
import re

def normalize_conversation_command(text: str) -> str:
    raw = " ".join(str(text or "").strip().split())
    lower = raw.casefold()
    if not lower:
        return raw
    if lower.startswith("/switch ") or lower in {"/clear","/history","/actions","/provider","/exit","/online","/local"}:
        return lower
    aliases = {
        "/clear": {"clear short term memory","clear short-term memory","clear conversation memory","clear current conversation","clear this conversation","clear chat history","clear conversation history","forget this conversation","forget the current conversation","reset conversation memory","reset short term memory","reset short-term memory"},
        "/history": {"show conversation history","show chat history","show my conversation history","list conversation history","list chat history","show history","show our history","what is our conversation history"},
        "/actions": {"list actions","show actions","show available actions","list available actions","what actions can you do","what actions are available","show conduit actions","list conduit actions"},
        "/provider": {"provider","which provider","which provider are you using","what provider are you using","show current provider","show provider","what model are you using","which model are you using","show current model"},
        "/exit": {"exit","quit","exit conduit","quit conduit","close conduit","close the conduit app","close the app","exit conversation","close conversation"},
    }
    for command, values in aliases.items():
        if lower in values:
            return command
    if re.fullmatch(r"(?:switch|use|change|connect|move)(?:\s+me)?\s+(?:to\s+)?gemini", lower) or lower in {"go online","switch to online mode"}:
        return "/switch gemini"
    if re.fullmatch(r"(?:switch|use|change|connect|move)(?:\s+me)?\s+(?:to\s+)?ollama", lower) or lower in {"go local","switch to local mode"}:
        return "/switch ollama"
    if re.fullmatch(r"(?:switch|use|change|connect|move)(?:\s+me)?\s+(?:to\s+)?(?:openai|open ai)", lower):
        return "/switch openai"
    return raw
