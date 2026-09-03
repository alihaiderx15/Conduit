
from types import SimpleNamespace
from pathlib import Path

import pytest

from conduit.messaging import service as ms


def test_whatsapp_config_includes_start_app_discovery():
    cfg = ms.SERVICE_CONFIG["whatsapp"]
    assert "WhatsApp" in cfg["start_app_names"]
    assert cfg["web_url"] == "https://web.whatsapp.com/"


def test_find_installed_client_prefers_registered_windows_app(monkeypatch):
    monkeypatch.setattr(ms, "_registered_start_apps", lambda: [
        {"name": "WhatsApp", "app_id": "5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App"},
        {"name": "Calculator", "app_id": "calc"},
    ])
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    found = ms.find_installed_client("whatsapp")
    assert found is not None
    assert found["kind"] == "start_app"
    assert "WhatsApp" in found["name"]


def test_launch_start_app_uses_windows_appsfolder(monkeypatch):
    monkeypatch.setattr(ms.sys, "platform", "win32")
    calls = []
    monkeypatch.setattr(
        ms.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(),
    )
    ok = ms.launch_installed_client(
        "whatsapp",
        {"kind": "start_app", "app_id": "package!App", "name": "WhatsApp"},
    )
    assert ok
    assert calls == [["explorer.exe", r"shell:AppsFolder\package!App"]]


class FakeAnalysis:
    def __init__(self, text):
        self.description = text


class FakeObserver:
    def __init__(self, text):
        self.text = text
        self.prompts = []
    async def analyze(self, prompt):
        self.prompts.append(prompt)
        return FakeAnalysis(self.text)


@pytest.mark.asyncio
async def test_login_classifier_requires_explicit_logged_in():
    agent = SimpleNamespace(
        router=SimpleNamespace(observer=FakeObserver("UNKNOWN\nThe page is unclear."))
    )
    state, reason = await ms.classify_login_state(agent, "whatsapp")
    assert state == "unknown"


@pytest.mark.asyncio
async def test_login_classifier_detects_logged_out():
    agent = SimpleNamespace(
        router=SimpleNamespace(observer=FakeObserver("LOGGED_OUT\nA QR code is visible."))
    )
    state, reason = await ms.classify_login_state(agent, "whatsapp")
    assert state == "logged_out"


def test_session_blocks_non_ready_before_contact_resolution():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    assert 'if readiness_state != "ready":' in source
    assert "stopped before searching for any contact" in source
