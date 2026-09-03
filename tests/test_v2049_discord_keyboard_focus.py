from types import SimpleNamespace
import pytest

from conduit.messaging import service as ms


class FocusTools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, confirmed=False):
        self.calls.append((call.name, dict(call.arguments)))
        if call.name == "system.activate_window":
            return SimpleNamespace(success=True, data={"title": "Discord", "handle": 77})
        if call.name == "system.active_window":
            return SimpleNamespace(success=True, data={"title": "Discord", "handle": 77})
        return SimpleNamespace(success=True, data={})


@pytest.mark.asyncio
async def test_force_discord_keyboard_focus_actively_activates_even_if_visible():
    tools = FocusTools()
    agent = SimpleNamespace(tools=tools)
    client = {"mode": "desktop", "window_title": "Discord", "window_handle": 77}

    title = await ms.force_service_keyboard_focus(agent, "discord", client, attempts=1)

    assert title == "Discord"
    names = [name for name, _ in tools.calls]
    assert names[0] == "system.activate_window"
    assert "system.active_window" in names


@pytest.mark.asyncio
async def test_discord_search_sends_ctrl_k_once_after_verified_focus_without_vision(monkeypatch):
    events = []

    async def focus(*args, **kwargs):
        events.append("focus")
        return "Discord"

    async def hotkey(agent, service, client, keys):
        events.append(("hotkey", tuple(keys)))

    class Tools:
        async def execute(self, call, confirmed=False):
            events.append(("tool", call.name, dict(call.arguments)))
            return SimpleNamespace(success=True, data={})

    async def forbidden_check(*args, **kwargs):
        raise AssertionError("Discord Ctrl+K fast path must not call vision")

    monkeypatch.setattr(ms, "force_service_keyboard_focus", focus)
    monkeypatch.setattr(ms, "service_hotkey", hotkey)
    monkeypatch.setattr(ms, "compact_messaging_check", forbidden_check)

    ok = await ms.open_contact_search(SimpleNamespace(tools=Tools()), "discord", {})
    assert ok is True
    assert events.count(("hotkey", ("ctrl", "k"))) == 1
    first_hotkey = events.index(("hotkey", ("ctrl", "k")))
    assert "focus" in events[:first_hotkey]

