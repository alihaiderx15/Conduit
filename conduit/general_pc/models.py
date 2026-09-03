"""Configuration models for Conduit's general-purpose PC agent."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GeneralPCAgentConfig:
    """Runtime settings for one general PC agent instance."""

    headless_browser: bool = False
    downloads_dir: Path | None = None
    max_iterations: int = 20
    max_decision_attempts: int = 2
    max_consecutive_failures: int = 3
    browser_timeout_ms: int = 12_000
    enable_desktop_control: bool = True
    enable_vision_when_available: bool = True
    prevent_blind_retries: bool = True
    provider_timeout_seconds: float = 30.0
    enable_deterministic_completion: bool = True
