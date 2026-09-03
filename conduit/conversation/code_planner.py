from __future__ import annotations
from dataclasses import dataclass
import re

@dataclass(frozen=True, slots=True)
class CodeIntent:
    action: str
    language: str = ""
    filename: str = ""
    package: str = ""
    path: str = ""

LANG_ALIASES = {
    "python":"python","py":"python","javascript":"javascript","js":"javascript",
    "typescript":"typescript","ts":"typescript","java":"java","c++":"cpp","cpp":"cpp",
    "c#":"csharp","csharp":"csharp","c":"c","go":"go","rust":"rust","php":"php",
    "ruby":"ruby","kotlin":"kotlin","swift":"swift","html":"html","css":"css","sql":"sql",
}

CODE_EXTS = "py|js|ts|java|c|cpp|cs|go|rs|php|rb|kt|swift|html|css|sql"


def detect_language_from_text(text: str) -> str:
    lowered=text.casefold()
    for token,lang in sorted(LANG_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", lowered):
            return lang
    return ""


def detect_filename(text: str) -> str:
    m=re.search(rf"(?i)\b(?:called|named|filename|file)\s+[\"']?([A-Za-z0-9_.-]+\.(?:{CODE_EXTS}))[\"']?", text)
    return m.group(1) if m else ""


def detect_path(text: str) -> str:
    # Absolute paths only. Relative/project path semantics belong to dev_agent.
    m=re.search(rf"(?i)([A-Z]:[\\/][^\n\r\"<>|?*]+\.(?:{CODE_EXTS}))", text)
    if m:
        return m.group(1).strip()
    m=re.search(rf"(?i)(/(?:[^\s/]+/)*[^\s/]+\.(?:{CODE_EXTS}))", text)
    return m.group(1).strip() if m else ""


def parse_code_intent(text: str, *, has_active_code: bool) -> CodeIntent | None:
    language=detect_language_from_text(text)
    filename=detect_filename(text)
    path=detect_path(text)

    if re.search(r"(?i)\b(?:generate|create|write|make|build)\b", text) and (
        language or re.search(r"(?i)\b(?:code|script|program|file)\b", text)
    ):
        return CodeIntent("generate", language, filename, path=path)
    if language and re.search(r"(?i)^\s*(?:give me\s+)?code\b", text):
        return CodeIntent("generate", language, filename, path=path)
    if not has_active_code:
        return None
    if re.search(r"(?i)\b(?:run|execute)\b", text): return CodeIntent("run",language,filename,path=path)
    if re.search(r"(?i)\b(?:test)\b", text): return CodeIntent("test",language,filename,path=path)
    if re.search(r"(?i)\b(?:fix|debug|repair)\b", text): return CodeIntent("debug",language,filename,path=path)
    if re.search(r"(?i)\b(?:optimi[sz]e|improve performance|make .* faster)\b", text): return CodeIntent("optimize",language,filename,path=path)
    if re.search(r"(?i)\b(?:review|code review|check this code)\b", text): return CodeIntent("review",language,filename,path=path)
    if re.search(r"(?i)\b(?:explain|what does this code|how does this code)\b", text): return CodeIntent("explain",language,filename,path=path)
    if re.search(r"(?i)\b(?:edit|change|modify|rewrite|replace|update)\b", text): return CodeIntent("edit",language,filename,path=path)
    if re.search(r"(?i)\binstall\b", text):
        m=re.search(r"(?i)\binstall\s+([A-Za-z0-9_.-]+)", text)
        return CodeIntent("install_dependency",language,filename,m.group(1) if m else "",path)
    return None
