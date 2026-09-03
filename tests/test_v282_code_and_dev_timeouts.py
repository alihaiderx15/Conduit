
from pathlib import Path


def source(path: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (root/path).read_text(encoding="utf-8")


def test_single_file_uses_unlimited_progress_watchdog():
    text = source("conduit/conversation/session.py")
    assert "async def _code_model_text(self, prompt: str, *, timeout: float | None = None)" in text
    assert "watchdog_interval_seconds=60" in text
    assert "overall_timeout=\"unlimited\"" in text
    assert "_code_model_text(prompt, timeout=None)" in text


def test_single_file_repair_uses_same_watchdog():
    text = source("conduit/conversation/session.py")
    assert "_code_model_text(repair_prompt, timeout=None)" in text
    assert "_code_model_text(repair_prompt, timeout=45.0)" not in text


def test_developer_agent_large_generation_gets_360_seconds():
    text = source("conduit/dev_agent/agent.py")
    assert 'watchdog_interval_seconds=60' in text
    assert "self.model_text(prompt, timeout=None)" in text


def test_developer_agent_has_no_overall_reasoning_timeout():
    text = source("conduit/dev_agent/agent.py")
    assert "async def model_text(self, prompt: str, *, timeout: float | None = None)" in text
    assert "run_with_progress_watchdog" in text


def test_no_old_120_second_multi_file_generation_timeout_remains():
    text = source("conduit/dev_agent/agent.py")
    assert "self.model_text(prompt, timeout=120.0)" not in text


def test_version_282():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
