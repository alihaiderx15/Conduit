
from types import SimpleNamespace

import pytest

from conduit.messaging import service as ms


class Result:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data or {}


class Element:
    visible = True
    enabled = True
    role = "textbox"
    label = "Search"
    text = ""
    confidence = 0.99
    center = (100, 100)


class Analysis:
    def __init__(self, elements):
        self.elements = elements


@pytest.mark.asyncio
async def test_whatsapp_uses_keyboard_search_fast_path(monkeypatch):
    calls = []

    async def fake_ensure(agent, service, client=None, attempts=3):
        calls.append(("focus", service))
        return "WhatsApp"

    async def fake_force_focus(agent, service, client=None, attempts=2):
        calls.append(("force_focus", service))
        return "WhatsApp"

    async def fake_hotkey(agent, service, client, keys):
        calls.append(("hotkey", tuple(keys)))

    async def fake_check(agent, service, client, prompt, allowed_tokens):
        calls.append(("compact", prompt))
        return ("SEARCH_READY", "SEARCH_READY")

    class Tools:
        async def execute(self, call, confirmed=False):
            calls.append((call.name, dict(call.arguments)))
            return Result(True, {})

    async def fake_reset(agent, service, client):
        calls.append(("reset", service))

    monkeypatch.setattr(ms, "ensure_service_foreground", fake_ensure)
    monkeypatch.setattr(ms, "force_service_keyboard_focus", fake_force_focus)
    monkeypatch.setattr(ms, "service_hotkey", fake_hotkey)
    monkeypatch.setattr(ms, "compact_messaging_check", fake_check)
    monkeypatch.setattr(ms, "reset_contact_search_state", fake_reset)

    result = await ms.open_contact_search(
        SimpleNamespace(tools=Tools()),
        "whatsapp",
        {"mode":"desktop","window_title":"WhatsApp"},
    )
    assert result is True
    assert ("hotkey", ("ctrl", "f")) in calls
    assert not any(item[0] == "compact" for item in calls)
    waits = [item[1].get("seconds") for item in calls if item[0] == "system.wait"]
    assert 1.0 in waits


def test_whatsapp_search_shortcut_is_adapter_configuration():
    assert ms.SERVICE_CONFIG["whatsapp"]["search_shortcuts"] == (("ctrl", "f"),)


def test_contact_resolution_no_longer_clicks_search_coordinates():
    from conduit.conversation import session
    source = open(session.__file__, encoding="utf-8").read()
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    executable = block[block.index("if not recipient.strip()"):]
    assert "open_contact_search" in executable
    assert "await click_service_element" not in executable


def test_event_bus_closes_worker_thread_coroutine():
    from conduit.events import bus
    source = open(bus.__file__, encoding="utf-8").read()
    assert 'close = getattr(result, "close", None)' in source
    assert "LOGGER.debug" in source
    assert "LOGGER.warning" not in source[source.index("def publish_nowait"):source.index("def emit_nowait")]
