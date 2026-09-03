
from pathlib import Path


def test_draft_not_typed_before_confirmation():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _execute_messaging_plan"):
        source.index("async def confirm_pending_message")
    ]
    assert "type_service_text(self.agent, service, client, final_message)" not in block
    assert "do NOT type or paste anything" in block


def test_confirmation_pastes_only_after_yes():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def confirm_pending_message"):
        source.index("def _could_be_youtube_request")
    ]
    assert 'ToolCall("clipboard.write", {"text": pending})' in block
    assert 'service_hotkey(self.agent, service, client, ("ctrl", "v"))' in block
    assert block.index('clipboard.write') < block.index('service_press(self.agent, service, client, "enter")')


def test_writer_forbids_names_placeholders_and_invented_context():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _compose_messaging_text"):
        source.index("async def _prepare_messaging_client")
    ]
    assert "[Recipient's Name]" in block
    assert "Do NOT add a greeting/salutation" in block
    assert "meeting" in block
    assert "rescheduling" in block
    assert "Second pass is a factuality/style audit" in block


def test_cancel_has_no_external_draft_cleanup():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def confirm_pending_message"):
        source.index("def _could_be_youtube_request")
    ]
    assert "Nothing was sent." in block
