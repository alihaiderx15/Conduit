
from __future__ import annotations
from datetime import datetime
import time
from .policy import ProactivePolicy
from .context_builder import ProactiveContextBuilder
from .cooldown import ProactiveCooldown

class ProactiveTriggerEngine:
    def __init__(self, context_builder: ProactiveContextBuilder, *, policy: ProactivePolicy | None = None) -> None:
        self.context_builder = context_builder
        self.policy = policy or ProactivePolicy()
        self.cooldown = ProactiveCooldown()
        self.last_user_activity = time.monotonic()
    def mark_user_activity(self) -> None: self.last_user_activity = time.monotonic()
    def evaluate(self, *, session_turns: int, recent_topic: str = "", now: datetime | None = None) -> str:
        if not self.policy.enabled: return ""
        now = now or datetime.now()
        if self.policy.quiet_now(now): return ""
        if time.monotonic() - self.last_user_activity < self.policy.idle_seconds: return ""
        if not self.cooldown.ready(self.policy.cooldown_seconds): return ""
        context = self.context_builder.build(session_turns, recent_topic=recent_topic)
        channels = context.get("favorite_channels") or []
        tasks = context.get("frequent_tasks") or []
        projects = context.get("active_projects") or []
        monitors = context.get("monitored_topics") or []
        topic = str(context.get("recent_topic") or "").strip()
        if monitors:
            msg = f"You've been idle for a while. Want me to check on {monitors[0]}?"
        elif topic:
            short = topic if len(topic) <= 90 else topic[:87] + "..."
            msg = f"You've been idle for a while. Want to continue: {short}?"
        elif projects:
            msg = f"You've been idle for a while. Want to continue working on {projects[0]}?"
        elif channels:
            msg = f"You've been idle for a while. Want me to play the latest video from {channels[0]}?"
        elif tasks:
            msg = f"You've been idle for a while. Your common Conduit task is {tasks[0]}. Want me to help with that?"
        elif session_turns:
            msg = "You've been idle for a while. Want to continue what we were working on?"
        else:
            msg = ""
        if msg: self.cooldown.mark()
        return msg
