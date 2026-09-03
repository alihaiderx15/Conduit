
from __future__ import annotations
import time
class ProactiveCooldown:
    def __init__(self) -> None: self.last_trigger_monotonic: float | None = None
    def ready(self, seconds: float) -> bool:
        return self.last_trigger_monotonic is None or time.monotonic() - self.last_trigger_monotonic >= seconds
    def mark(self) -> None: self.last_trigger_monotonic = time.monotonic()
