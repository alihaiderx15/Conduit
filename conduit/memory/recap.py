
from __future__ import annotations
from .manager import MemoryManager
from .session import ShortTermSessionMemory

class SessionRecapManager:
    def __init__(self, manager: MemoryManager) -> None:
        self.manager = manager

    def summarize_and_store(self, session: ShortTermSessionMemory) -> str:
        summary = session.deterministic_recap()
        if not summary: return ""
        self.manager.repository.add_session_recap(summary, metadata={"turn_count": len(session.turns)})
        return summary

    def resume_context(self, *, consume: bool = True) -> str:
        recap = self.manager.repository.latest_unconsumed_recap()
        if recap is None: return ""
        if consume: self.manager.repository.consume_recap(recap.id)
        return recap.summary
