
from pathlib import Path


def test_contact_search_uses_exact_user_query_and_first_result():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert "searching EXACTLY" in block or "searched EXACTLY" in block
    assert "Do not return JSON and do not choose among the results" in block
    assert "RESULTS_READY" in block


def test_first_result_is_opened_by_keyboard_not_vision_click():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert "click_service_element" not in block
    assert '"down"' in block
    assert '"enter"' in block


def test_open_chat_response_uses_requested_query_not_invented_contact_name():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    execute = source[
        source.index("async def _execute_messaging_plan"):
        source.index("async def confirm_pending_message")
    ]
    assert "requested_recipient" in execute
    assert "opened the first" in execute
    assert "search result for" in execute


def test_send_path_uses_direct_chat_focus_not_composer_coordinates():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    execute = source[
        source.index("async def _execute_messaging_plan"):
        source.index("async def confirm_pending_message")
    ]
    assert "locate_message_composer_center" not in execute
    assert "click_service_xy" not in execute
    assert "type_service_text(self.agent, service, client, final_message)" not in execute
    assert "do NOT type or paste anything" in execute
