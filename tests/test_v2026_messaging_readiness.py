
from types import SimpleNamespace

import pytest

from conduit.messaging import service as ms


class FakeAnalysis:
    def __init__(self, text):
        self.description = text


class SequencedObserver:
    def __init__(self, texts):
        self.texts = list(texts)
    async def analyze(self, prompt):
        text = self.texts.pop(0) if self.texts else "UNKNOWN\nNo state."
        return FakeAnalysis(text)


class FakeTools:
    async def execute(self, call, confirmed=False):
        if call.name == "system.list_windows":
            return SimpleNamespace(
                success=True,
                data={"windows":[{"title":"WhatsApp","handle":123}]},
            )
        return SimpleNamespace(success=True, data={"title":"WhatsApp"})


class FakeEvents:
    def __init__(self):
        self.items=[]
    async def emit(self, name, **kwargs):
        self.items.append((name, kwargs))


@pytest.mark.asyncio
async def test_state_classifier_distinguishes_loading_from_logout():
    agent = SimpleNamespace(
        router=SimpleNamespace(observer=SequencedObserver([
            "LOADING\nRecent chats are still loading."
        ]))
    )
    state, reason = await ms.classify_client_state(agent, "whatsapp")
    assert state == "loading"


@pytest.mark.asyncio
async def test_readiness_retries_loading_until_ready(monkeypatch):
    monkeypatch.setattr(ms, "desktop_app_running", lambda service: True)
    observer = SequencedObserver([
        "LOADING\nA spinner is visible.",
        "UNKNOWN\nThe interface is partially loaded.",
        "READY\nThe normal chat list and search control are visible.",
    ])
    agent = SimpleNamespace(
        router=SimpleNamespace(observer=observer),
        tools=FakeTools(),
        events=FakeEvents(),
    )
    state, reason, evidence = await ms.wait_until_client_ready(
        agent,
        "whatsapp",
        {"mode":"desktop"},
        timeout_seconds=5,
        poll_seconds=0.01,
    )
    assert state == "ready"
    assert evidence["attempts"] == 3


@pytest.mark.asyncio
async def test_readiness_stops_immediately_on_logged_out(monkeypatch):
    monkeypatch.setattr(ms, "desktop_app_running", lambda service: False)
    observer = SequencedObserver([
        "LOGGED_OUT\nA QR code and Link a device instructions are visible."
    ])
    agent = SimpleNamespace(
        router=SimpleNamespace(observer=observer),
        tools=FakeTools(),
        events=FakeEvents(),
    )
    state, reason, evidence = await ms.wait_until_client_ready(
        agent,
        "whatsapp",
        {"mode":"web"},
        timeout_seconds=5,
        poll_seconds=0.01,
    )
    assert state == "logged_out"
    assert evidence["attempts"] == 1


def test_session_uses_readiness_loop():
    from conduit.conversation import session
    from pathlib import Path
    source = Path(session.__file__).read_text(encoding="utf-8")
    assert "wait_until_client_ready" in source
    assert 'readiness_state != "ready"' in source
    assert "timeout_seconds=90.0" in source


def test_shell_reports_waiting_state():
    from pathlib import Path
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "messaging.client.state" in source
    assert "waiting for" in source
    assert "to become ready" in source
