
from types import SimpleNamespace

import pytest

from conduit.messaging import service as ms


class Result:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data or {}


class NeverFocusTools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, confirmed=False):
        self.calls.append((call.name, dict(call.arguments)))
        if call.name == "system.active_window":
            return Result(True, {"title": "ChatGPT - Opera"})
        if call.name == "system.activate_window":
            return Result(True, {"title": "WhatsApp"})
        return Result(True, {})


@pytest.mark.asyncio
async def test_focus_recovery_fails_only_after_three_attempts():
    tools = NeverFocusTools()
    agent = SimpleNamespace(tools=tools, events=None)
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        await ms.ensure_service_foreground(
            agent,
            "whatsapp",
            {"mode": "desktop", "window_title": "WhatsApp"},
            attempts=3,
        )

    activations = [
        call for call in tools.calls
        if call[0] == "system.activate_window"
    ]
    assert len(activations) == 3


@pytest.mark.asyncio
async def test_click_retries_when_click_itself_loses_focus(monkeypatch):
    states = iter([
        "WhatsApp",          # ensure before click 1
        "ChatGPT - Opera",   # after click 1 -> lost
        "WhatsApp",          # recovery verify
        "WhatsApp",          # ensure before click 2
        "WhatsApp",          # after click 2 -> success
    ])

    async def fake_active(agent):
        title = next(states, "WhatsApp")
        return {"title": title, "handle": 0}

    async def fake_ensure(agent, service, client=None, attempts=3):
        identity = await fake_active(agent)
        if "whatsapp" in identity["title"].casefold():
            return identity["title"]
        # simulate successful reactivation/verification
        identity = await fake_active(agent)
        return identity["title"]

    clicks = []

    async def fake_click(agent, element):
        clicks.append(element)

    monkeypatch.setattr(ms, "active_window_identity", fake_active)
    monkeypatch.setattr(ms, "ensure_service_foreground", fake_ensure)
    monkeypatch.setattr(ms, "click_element", fake_click)

    class DummyTools:
        async def execute(self, call, confirmed=False):
            return Result(True, {})

    element = SimpleNamespace(center=(100, 100))
    await ms.click_service_element(
        SimpleNamespace(tools=DummyTools()),
        "whatsapp",
        {"mode": "desktop", "window_title": "WhatsApp"},
        element,
        attempts=3,
    )
    assert len(clicks) == 2


def test_no_restore_false_immediate_failure_remains():
    source = open(ms.__file__, encoding="utf-8").read()
    assert "restore=False" not in source
    assert "attempts: int = 3" in source
    assert "after {tries} attempts" in source


def test_shell_shows_focus_retry_progress():
    from pathlib import Path
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "messaging.focus.recovery" in source
    assert "restoring focus" in source
