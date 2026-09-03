
from types import SimpleNamespace

import pytest

from conduit.messaging import service as ms


class Result:
    def __init__(self, success=True, data=None):
        self.success = success
        self.data = data or {}


class FocusTools:
    def __init__(self, active_titles):
        self.active_titles = list(active_titles)
        self.calls = []

    async def execute(self, call, confirmed=False):
        self.calls.append((call.name, dict(call.arguments)))
        if call.name == "system.active_window":
            title = self.active_titles.pop(0) if self.active_titles else "WhatsApp"
            return Result(True, {"title": title})
        if call.name == "system.activate_window":
            return Result(True, {"title": "WhatsApp"})
        return Result(True, {})


@pytest.mark.asyncio
async def test_foreground_guard_accepts_whatsapp():
    agent = SimpleNamespace(tools=FocusTools(["WhatsApp"]))
    title = await ms.ensure_service_foreground(
        agent, "whatsapp", {"mode":"desktop","window_title":"WhatsApp"}
    )
    assert title == "WhatsApp"


@pytest.mark.asyncio
async def test_foreground_guard_reactivates_wrong_window():
    tools = FocusTools(["ChatGPT - Opera", "WhatsApp"])
    agent = SimpleNamespace(tools=tools)
    title = await ms.ensure_service_foreground(
        agent, "whatsapp", {"mode":"desktop","window_title":"WhatsApp"}
    )
    assert title == "WhatsApp"
    assert any(name == "system.activate_window" for name, _ in tools.calls)


@pytest.mark.asyncio
async def test_foreground_guard_recovers_focus_escape():
    tools = FocusTools(["ChatGPT - Opera", "WhatsApp"])
    agent = SimpleNamespace(tools=tools)
    title = await ms.ensure_service_foreground(
        agent,
        "whatsapp",
        {"mode":"desktop","window_title":"WhatsApp"},
        attempts=3,
    )
    assert title == "WhatsApp"
    assert any(name == "system.activate_window" for name, _ in tools.calls)


def test_contact_search_uses_guarded_adapter_search_not_blind_fallback():
    from conduit.conversation import session
    source = open(session.__file__, encoding="utf-8").read()
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert "open_contact_search" in block
    assert '("ctrl", "f")' not in block
    assert "type_service_text" in block


def test_send_commit_verifies_approved_draft_before_enter():
    from conduit.conversation import session
    source = open(session.__file__, encoding="utf-8").read()
    block = source[
        source.index("async def confirm_pending_message"):
        source.index("def _could_be_youtube_request")
    ]
    assert "approved draft" in block.casefold()
    assert "DRAFT_PRESENT" in block
    assert "service_press" in block
    assert block.index("DRAFT_PRESENT") < block.index('service_press(self.agent')
