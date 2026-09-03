from types import SimpleNamespace
from pathlib import Path
import pytest

import conduit.messaging.service as ms


@pytest.mark.asyncio
async def test_discord_cold_start_switches_to_compact_current_screen_probe(monkeypatch):
    broad_calls = 0
    compact_calls = 0

    async def evidence(*args, **kwargs):
        return {"process_running": True, "window_found": True, "window_title": "Discord"}

    async def broad(*args, **kwargs):
        nonlocal broad_calls
        broad_calls += 1
        return "loading", "Discord splash visible"

    async def compact(*args, **kwargs):
        nonlocal compact_calls
        compact_calls += 1
        return "ready", "Normal Discord server/sidebar/chat UI visible"

    class Tools:
        async def execute(self, call, confirmed=False):
            return SimpleNamespace(success=True, data={})

    monkeypatch.setattr(ms, "_messaging_window_evidence", evidence)
    monkeypatch.setattr(ms, "classify_client_state", broad)
    monkeypatch.setattr(ms, "classify_discord_ready_compact", compact)

    agent = SimpleNamespace(tools=Tools(), events=None)
    state, reason, details = await ms.wait_until_client_ready(
        agent, "discord", {"mode": "desktop"}, timeout_seconds=5, poll_seconds=0.01
    )
    assert state == "ready"
    assert broad_calls == 1
    assert compact_calls == 1
    assert details["attempts"] == 2


@pytest.mark.asyncio
async def test_compact_probe_treats_normal_discord_shell_as_ready(monkeypatch):
    async def observe(agent, prompt):
        assert "CURRENT screenshot" in prompt
        assert "server icons/sidebar" in prompt
        return SimpleNamespace(description="READY\nNormal Discord sidebar and chat content are visible.")

    monkeypatch.setattr(ms, "observe_messaging_description", observe)
    state, reason = await ms.classify_discord_ready_compact(SimpleNamespace())
    assert state == "ready"


def test_default_readiness_poll_is_one_second():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def wait_until_client_ready"):source.index("async def active_window_identity")]
    assert "poll_seconds: float = 1.0" in block
