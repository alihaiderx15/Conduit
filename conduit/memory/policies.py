"""Privacy and retention policies for persistent memory."""

from __future__ import annotations

import re
from dataclasses import dataclass


class SensitiveMemoryError(ValueError):
    """Raised when content appears to contain credentials or secrets."""


_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|passwd|secret)\b\s*[:=]\s*\S+"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


@dataclass(frozen=True, slots=True)
class MemoryPolicy:
    """Validate values before they are written to persistent memory."""

    max_value_length: int = 20_000

    def validate(self, key: str, value: str) -> None:
        if not key.strip():
            raise ValueError("Memory key cannot be empty.")
        if not value.strip():
            raise ValueError("Memory value cannot be empty.")
        if len(value) > self.max_value_length:
            raise ValueError(f"Memory value exceeds {self.max_value_length} characters.")
        combined = f"{key}: {value}"
        if any(pattern.search(combined) for pattern in _SECRET_PATTERNS):
            raise SensitiveMemoryError(
                "This content appears to contain a password, API key, token, or private key and was not stored."
            )
