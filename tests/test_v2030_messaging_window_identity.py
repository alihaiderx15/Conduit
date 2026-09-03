
from types import SimpleNamespace

import pytest

from conduit.messaging import service as ms


class Result:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data or {}


class Tools:
    def __init__(self, identities):
        self.identities = list(identities)
        self.calls = []

    async def execute(self, call, confirmed=False):
        self.calls.append((call.name, dict(call.arguments)))
        if call.name == "system.active_window":
            value = self.identities.pop(0) if self.identities else {"title":"Maryam","handle":42}
            return Result(True, value)
        if call.name == "system.activate_window":
            return Result(True, {"title":"WhatsApp","handle":42})
        return Result(True, {})


@pytest.mark.asyncio
async def test_same_handle_counts_as_same_whatsapp_even_if_title_changes():
    agent = SimpleNamespace(
        tools=Tools([{"title":"Maryam","handle":42}]),
        events=None,
    )
    client = {
        "mode":"desktop",
        "window_title":"WhatsApp",
        "window_handle":42,
    }
    title = await ms.ensure_service_foreground(agent, "whatsapp", client)
    assert title == "Maryam"
    assert not any(name == "system.activate_window" for name, _ in agent.tools.calls)


def test_window_identity_prefers_handle_over_title():
    client = {"window_title":"WhatsApp", "window_handle":99}
    assert ms._window_belongs_to_service(
        "whatsapp",
        {"title":"Completely Different Title", "handle":99},
        client,
    )
    assert not ms._window_belongs_to_service(
        "whatsapp",
        {"title":"WhatsApp", "handle":100},
        client,
    )


def test_keyboard_actions_do_not_post_reactivate():
    source = open(ms.__file__, encoding="utf-8").read()
    type_block = source[
        source.index("async def type_service_text"):
        source.index("async def service_hotkey")
    ]
    hotkey_block = source[
        source.index("async def service_hotkey"):
        source.index("async def reset_contact_search_state")
    ]
    assert type_block.count("ensure_service_foreground") == 1
    assert hotkey_block.count("ensure_service_foreground") == 1


def test_session_preserves_pending_window_handle():
    from conduit.conversation import session
    source = open(session.__file__, encoding="utf-8").read()
    assert "pending_window_handle" in source
