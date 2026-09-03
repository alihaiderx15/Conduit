
from pathlib import Path


def test_messaging_search_no_longer_requires_structured_json():
    from conduit.messaging import service
    source = Path(service.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def open_contact_search"):
        source.index("async def service_press")
    ]
    assert "compact_messaging_check" in block
    assert "observe_service_screen" not in block
    assert "SEARCH_READY" in block


def test_contact_resolution_uses_compact_result_and_chat_checks():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    assert "RESULTS_READY" in block
    assert "CHAT_OPEN" in block
    assert "observe_service_screen" not in block


def test_message_composer_uses_tiny_coordinate_protocol():
    from conduit.messaging import service
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "async def locate_message_composer_center" in source
    assert "COMPOSER x y" in source
    assert "NO_COMPOSER" in source


def test_send_confirmation_uses_compact_non_json_checks():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def confirm_pending_message"):
        source.index("def _could_be_youtube_request")
    ]
    assert "DRAFT_PRESENT" in block
    assert "SENT_PRESENT" in block
    assert "observe_service_screen" not in block
