
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime

@dataclass(slots=True)
class ProactivePolicy:
    enabled: bool = True
    idle_seconds: float = 15 * 60
    cooldown_seconds: float = 2 * 60 * 60
    quiet_start_hour: int = 23
    quiet_end_hour: int = 7
    def quiet_now(self, now: datetime) -> bool:
        hour = now.hour
        if self.quiet_start_hour > self.quiet_end_hour:
            return hour >= self.quiet_start_hour or hour < self.quiet_end_hour
        return self.quiet_start_hour <= hour < self.quiet_end_hour
