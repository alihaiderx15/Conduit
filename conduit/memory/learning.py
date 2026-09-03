
from __future__ import annotations
import re
from .manager import MemoryManager
from .models import MemoryCategory

class LongTermMemoryLearner:
    """Persist stable directives and repeated behavior, never the full transcript."""
    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    @staticmethod
    def _scope(text: str) -> str:
        lower = text.casefold()
        if any(x in lower for x in ("code", "coding", "python", "developer", "project files")): return "code"
        if any(x in lower for x in ("youtube", "channel", "video")): return "youtube"
        if any(x in lower for x in ("browser", "chrome", "opera", "firefox", "edge", "tab")): return "browser"
        if any(x in lower for x in ("game", "steam", "epic", "apex", "tekken")): return "games"
        if any(x in lower for x in ("file", "pdf", "docx", "excel", "image", "video")): return "files"
        return "general"

    def remember_explicit_directive(self, text: str) -> dict | None:
        lower = text.casefold()
        if not any(marker in lower for marker in ("always ", "from now on", "whenever i ", "every time i ", "i want you to always", "remember to always")):
            return None
        scope = self._scope(text)
        key = "behavior"
        value = " ".join(text.split())

        code_words = any(term in lower for term in ("generated code","code file","code files","coding file","coding files","generated files","coding","code"))
        save_words = any(term in lower for term in ("save ","store ","put "))
        if code_words and save_words:
            path_match = re.search(r'(?i)([A-Za-z]:\\[^\r\n]*)', text)
            drive_match = re.search(r'(?i)\b([A-Za-z])\s+drive\b', text)
            if path_match:
                raw = re.sub(r'\\+$', r'\\', path_match.group(1).strip())
                scope, key, value = "code", "output_directory", raw
            elif drive_match:
                scope, key, value = "code", "output_directory", drive_match.group(1).upper() + ":\\"

        self.manager.repository.upsert_directive(scope, key, value, source_text=text)
        self.manager.remember(
            f"directive:{scope}:{key}", value,
            category=MemoryCategory.DIRECTIVE,
            importance=0.98,
            source="explicit_user_instruction",
            metadata={"scope": scope, "source_text": text},
        )
        return {"scope": scope, "key": key, "value": value}

    def _remember_explicit_directive(self, text: str) -> None:
        self.remember_explicit_directive(text)

    def _learn_youtube(self, text: str) -> None:
        lower = text.casefold()
        if "youtube" not in lower and "channel" not in lower and "video" not in lower: return
        patterns = (
            r'(?i)\b(?:latest|newest|recent)\s+(?:video|upload)\s+(?:from|by)\s+(.+?)(?:\s+on\s+youtube)?$',
            r'(?i)\b(?:from|by)\s+([A-Za-z0-9_. &\'’-]{2,60})\s+(?:channel|on youtube)\b',
            r'(?i)\b(?:open|play)\s+([A-Za-z0-9_. &\'’-]{2,60})\s+(?:youtube\s+)?channel\b',
        )
        for pattern in patterns:
            match = re.search(pattern, text.strip())
            if match:
                channel = " ".join(match.group(1).split()).strip(" .,-")
                if channel and len(channel) <= 80:
                    self.manager.repository.increment_behavior("youtube_channel", channel, score_delta=1.5, metadata={"source":"conversation"})
                    return

    def _learn_app(self, text: str) -> None:
        match = re.match(r'(?i)^\s*(?:please\s+)?(?:open|launch|start)\s+([A-Za-z0-9_. +&\'-]{2,50})(?:\s+and\s+.*)?$', text.strip())
        if not match: return
        app = " ".join(match.group(1).split()).strip()
        if any(app.casefold().startswith(x) for x in ("youtube","reddit","gmail","github","wikipedia")): return
        self.manager.repository.increment_behavior("app", app, score_delta=1.0, metadata={"source":"conversation"})

    def _learn_identity(self, text: str) -> None:
        """Remember a user-provided name even when it appears in an introduction."""
        # Accept natural introductions such as:
        # "Hi, my name is Ali and I like to automate things."
        # The old whole-message regex missed these and therefore never saved
        # the identity fact. ``nad`` is accepted as a common typo for ``and``.
        patterns = (
            r"(?i)\b(?:my\s+name\s+is|call\s+me)\s+"
            r"([A-Za-z][A-Za-z\'-]{0,59}?)(?=\s+(?:and|but|because|i|i\'m|i\s+am|nad)\b|[.!?,;]|$)",
            r"(?i)\b(?:i\s+am|i\'m)\s+"
            r"([A-Za-z][A-Za-z\'-]{0,59}?)(?=\s+(?:and|but|because|i|i\'m|i\s+am|nad)\b|[.!?,;]|$)",
        )
        match = next((re.search(pattern, text) for pattern in patterns if re.search(pattern, text)), None)
        if not match:
            return
        name = " ".join(match.group(1).split()).strip(" .")
        if not name or name.casefold() in {"fine", "good", "okay", "ok", "here", "ready"}:
            return
        self.manager.remember(
            "user:name", name, category=MemoryCategory.PREFERENCE, importance=0.95,
            source="explicit_user_fact", metadata={"kind": "identity", "field": "name"},
        )


    @staticmethod
    def _clean_fact_value(value: str) -> str:
        value = " ".join(str(value or "").split()).strip(" .,!?:;\"")
        # Stop at a new first-person clause so one sentence can yield several memories.
        value = re.split(r"(?i)\s+(?:and|but|nad)\s+(?=i\b|my\b)", value, maxsplit=1)[0].strip()
        return value

    def _learn_explicit_profile_facts(self, text: str) -> None:
        """Learn durable facts/preferences stated naturally by the user.

        This is intentionally category-based rather than question-specific: a single
        message may contain a name plus likes, dislikes, occupation, location, etc.
        The full transcript remains session memory; only clearly user-asserted, useful
        profile facts are promoted to long-term memory.
        """
        patterns = (
            (r"(?i)\bi\s+(?:really\s+)?(?:like|love|enjoy)\s+(?:to\s+)?(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:likes", MemoryCategory.PREFERENCE, 0.86),
            (r"(?i)\bi\s+(?:do\s+not|don't|dont|dislike|hate)\s+(?:like\s+)?(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:dislikes", MemoryCategory.PREFERENCE, 0.84),
            (r"(?i)\bi\s+prefer\s+(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:preference", MemoryCategory.PREFERENCE, 0.88),
            (r"(?i)\bmy\s+favou?rite\s+([A-Za-z][A-Za-z _-]{1,30})\s+is\s+(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:favorite", MemoryCategory.PREFERENCE, 0.90),
            (r"(?i)\bi\s+(?:work|am working)\s+as\s+(?:an?\s+)?(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:occupation", MemoryCategory.FACT, 0.82),
            (r"(?i)\bi\s+live\s+in\s+(.+?)(?=(?:[.!?;]|$|\s+(?:and|but|nad)\s+(?:i|my)\b))", "user:location", MemoryCategory.FACT, 0.80),
        )
        for pattern, base_key, category, importance in patterns:
            for match in re.finditer(pattern, text):
                groups = match.groups()
                if base_key == "user:favorite":
                    kind = self._clean_fact_value(groups[0]).casefold().replace(" ", "_")
                    value = self._clean_fact_value(groups[1])
                    key = f"user:favorite:{kind}" if kind else base_key
                else:
                    value = self._clean_fact_value(groups[-1])
                    key = base_key
                if not value or len(value) > 240:
                    continue
                self.manager.remember(
                    key, value, category=category, importance=importance,
                    source="explicit_user_fact",
                    metadata={"kind": "profile", "source_text": text},
                )

    def _learn_task_kind(self, text: str) -> None:
        lower = text.casefold(); kind = None
        if any(x in lower for x in ("youtube","video","channel")): kind = "youtube"
        elif re.search(r"\b(?:open|launch|close)\b", lower): kind = "apps"
        elif any(x in lower for x in ("code","python","cpp","project")): kind = "coding"
        elif any(x in lower for x in ("pdf","docx","excel","file","image","video")): kind = "files"
        elif any(x in lower for x in ("steam","epic","game","update apex","update tekken")): kind = "games"
        if kind: self.manager.repository.increment_behavior("task_kind", kind, score_delta=0.5)

    def observe(self, user: str, assistant: str = "") -> None:
        text = str(user or "").strip()
        if not text: return
        try:
            self._remember_explicit_directive(text)
            self._learn_identity(text)
            self._learn_explicit_profile_facts(text)
            self._learn_youtube(text)
            self._learn_app(text)
            self._learn_task_kind(text)
        except Exception:
            return
