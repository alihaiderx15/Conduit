
from pathlib import Path


def test_contact_search_resets_previous_search_state():
    from conduit.messaging import service
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "async def reset_contact_search_state" in source
    block = source[
        source.index("async def open_contact_search"):
        source.index("async def service_press")
    ]
    assert "reset_contact_search_state" in block


def test_contact_open_requires_post_selection_verification():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert "Verify a real chat opened with a compact response" in block
    assert "CHAT_OPEN" in block
    assert "compact_messaging_check" in block
    assert "couldn't verify that the chat" in block
    assert "actually opened" in block


def test_open_chat_success_is_after_keyboard_selection_and_verification():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert 'service_press(self.agent, service, client, "down")' in block
    assert 'service_press(self.agent, service, client, "enter")' in block
    assert block.index('service_press(self.agent, service, client, "enter")') < block.index("CHAT_OPEN")
    assert block.index("CHAT_OPEN") < block.rindex('return {')
