from pathlib import Path


def test_discord_native_ranking_path_has_no_vision_between_search_and_enter():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    discord_start = block.index('if service == "discord":')
    discord_end = block.index('else:', discord_start)
    discord = block[discord_start:discord_end]
    assert 'search_text = requested_recipient' in block
    assert "force_service_keyboard_focus" in discord
    assert 'service_press(self.agent, service, client, "enter")' in discord
    assert "compact_messaging_check" not in discord
    assert "observe_messaging_description" not in discord
    assert "open_matching_discord_recipient" not in discord


def test_discord_final_open_path_skips_vision_but_preserves_human_send_confirmation():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    resolve = source[
        source.index("async def _resolve_messaging_contact"):
        source.index("async def _execute_messaging_plan")
    ]
    marker = '# Discord\'s Quick Switcher + Enter path is deterministic'
    discord_tail = resolve[resolve.index(marker):resolve.index('verify_prompt =', resolve.index(marker))]
    assert "compact_messaging_check" not in discord_tail
    assert "force_service_keyboard_focus" in discord_tail

    confirm = source[source.index("async def confirm_pending_message"):source.index("def _could_be_youtube_request")]
    assert 'ToolCall("clipboard.write", {"text": pending})' in confirm
    assert 'service_hotkey(self.agent, service, client, ("ctrl", "v"))' in confirm
    assert 'service_press(self.agent, service, client, "enter")' in confirm
