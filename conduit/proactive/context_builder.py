
from __future__ import annotations
from conduit.memory import MemoryManager

class ProactiveContextBuilder:
    def __init__(self, memory: MemoryManager | None) -> None:
        self.memory = memory

    def build(self, session_turns: int, recent_topic: str = "") -> dict:
        context = {"session_turns": int(session_turns), "recent_topic": str(recent_topic or "").strip()}
        if self.memory is None:
            return context
        context["favorite_channels"] = [x.value for x in self.memory.top_behaviors("youtube_channel", limit=3)]
        context["frequent_apps"] = [x.value for x in self.memory.top_behaviors("app", limit=3)]
        context["frequent_tasks"] = [x.value for x in self.memory.top_behaviors("task_kind", limit=3)]
        try:
            context["active_projects"] = [x.name for x in self.memory.repository.list_projects(limit=3)]
        except Exception:
            context["active_projects"] = []
        monitored = []
        try:
            for record in self.memory.repository.list_memories():
                key = record.key.casefold()
                meta = record.metadata or {}
                if key.startswith("monitor:") or bool(meta.get("monitor")):
                    monitored.append(record.value)
        except Exception:
            pass
        context["monitored_topics"] = monitored[:3]
        return context
