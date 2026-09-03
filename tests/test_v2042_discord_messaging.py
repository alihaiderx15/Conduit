from pathlib import Path
from types import SimpleNamespace

import pytest

from conduit.conversation.session import ConversationSession
from conduit.messaging import service as ms
from conduit.messaging.planner import AIMessagingRouter


def test_discord_is_registered_as_visible_messaging_service():
    cfg = ms.SERVICE_CONFIG["discord"]
    assert "Discord.exe" in cfg["processes"]
    assert cfg["web_url"] == "https://discord.com/channels/@me"
    assert ("ctrl", "k") in cfg["search_shortcuts"]


def test_find_installed_discord_can_use_updater_path(monkeypatch, tmp_path):
    update = tmp_path / "Update.exe"
    update.write_text("x")
    monkeypatch.setitem(ms.SERVICE_CONFIG["discord"], "known_paths", (str(update),))
    monkeypatch.setattr(ms, "_registered_start_apps", lambda: [])
    found = ms.find_installed_client("discord")
    assert found is not None
    assert found["kind"] == "win32"
    assert found["path"].endswith("Update.exe")



def test_launch_discord_updater_uses_process_start(monkeypatch, tmp_path):
    update = tmp_path / "Update.exe"
    update.write_text("x")
    calls = []
    monkeypatch.setattr(ms.sys, "platform", "win32")
    monkeypatch.setattr(ms, "launch_detached_process", lambda args: calls.append(args) or SimpleNamespace())
    ok = ms.launch_installed_client("discord", {"kind": "win32", "path": str(update)})
    assert ok is True
    assert calls == [[str(update), "--processStart", "Discord.exe"]]


def test_discord_web_fallback_points_to_direct_messages():
    assert ms.SERVICE_CONFIG["discord"]["web_url"].endswith("/channels/@me")

def test_discord_routes_as_messaging_request_and_extracts_literal_send():
    session = object.__new__(ConversationSession)
    session._messaging_context = {}
    assert session._could_be_messaging_request("open discord chat with basit")
    assert session._could_be_messaging_request("message basit on discord")
    recipient, message = session._inline_messaging_send(
        "open the chat with Basit on discord and message Hi"
    )
    assert recipient == "Basit"
    assert message == "Hi"


def test_discord_fallback_open_chat_plan():
    plan = ConversationSession._fallback_messaging_plan(
        "open chat with Basit on discord"
    )
    assert plan is not None
    assert plan.action == "messaging.open_chat"
    assert plan.service == "discord"
    assert plan.recipient == "Basit"


@pytest.mark.asyncio
async def test_ai_router_accepts_discord():
    class Provider:
        async def chat(self, messages, *, model):
            return SimpleNamespace(text='null')

        async def specialist_chat(self, messages, *, model):
            return SimpleNamespace(text='{"action":"messaging.send","service":"discord","recipient":"Basit","message":"Hi","compose_instruction":""}')

    plan = await AIMessagingRouter(Provider(), model="test").plan(
        "send Basit Hi on Discord"
    )
    assert plan is not None
    assert plan.service == "discord"
    assert plan.action == "messaging.send"


def test_discord_fast_search_trusts_ctrl_k_after_verified_focus():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def open_contact_search"):source.index("async def service_press")]
    discord_block = block[block.index('if service == "discord"'):block.index('await emit_messaging_stage', block.index('if service == "discord"'))]
    assert "ensure_discord_direct_messages" not in discord_block
    assert "force_service_keyboard_focus" in discord_block
    assert '("ctrl", "k")' in discord_block
    assert 'seconds": 2.0' in discord_block
    assert "compact_messaging_check" not in discord_block
    assert "observe_" not in discord_block


def test_discord_uses_native_first_ranked_result_instead_of_vision_identity_matching():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def _resolve_messaging_contact"):source.index("async def _execute_messaging_plan")]
    discord = block[block.index('if service == "discord"'):block.index('else:', block.index('if service == "discord"'))]
    assert "force_service_keyboard_focus" in discord
    assert 'service_press(self.agent, service, client, "enter")' in discord
    assert "open_matching_discord_recipient" not in discord
    assert "observe_messaging_description" not in discord


def test_safe_send_confirmation_remains_service_generic_for_discord():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def confirm_pending_message"):source.index("def _could_be_youtube_request")]
    assert 'ToolCall("clipboard.write", {"text": pending})' in block
    assert 'service_hotkey(self.agent, service, client, ("ctrl", "v"))' in block
    assert 'service_press(self.agent, service, client, "enter")' in block

@pytest.mark.asyncio
async def test_discord_foreground_rebinds_when_electron_replaces_startup_hwnd():
    class Result:
        def __init__(self, success=True, data=None):
            self.success = success
            self.data = data or {}

    class Tools:
        def __init__(self):
            self.calls = []

        async def execute(self, call, confirmed=False):
            self.calls.append((call.name, dict(call.arguments)))
            if call.name == "system.active_window":
                return Result(True, {"title": "Discord", "handle": 222})
            if call.name == "system.activate_window":
                return Result(True, {})
            return Result(True, {})

    tools = Tools()
    agent = SimpleNamespace(tools=tools, events=None)
    client = {
        "mode": "desktop",
        "window_title": "Discord",
        "window_handle": 111,
    }

    title = await ms.ensure_service_foreground(agent, "discord", client, attempts=3)

    assert title == "Discord"
    assert client["window_handle"] == 222
    assert not any(name == "system.activate_window" for name, _ in tools.calls)


def test_shell_prints_messaging_stage_diagnostics():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert 'event.name == "messaging.stage"' in source
    assert "[Discord messaging]" not in source  # remains service-generic
    assert "detail" in source

@pytest.mark.asyncio
async def test_discord_desktop_readiness_does_not_skip_vision(monkeypatch):
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def wait_until_client_ready"):source.index("async def active_window_identity")]
    assert "classify_client_state(agent, service)" in block
    assert "readiness_basis" not in block


def test_discord_dm_verification_has_explicit_logged_out_guard():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def ensure_discord_direct_messages"):source.index("async def open_contact_search")]
    assert "DISCORD_LOGGED_OUT" in block
    assert "Discord isn't logged in" in block

@pytest.mark.asyncio
async def test_discord_recipient_search_types_plain_name_and_opens_first_ranked_result(monkeypatch):
    typed = []
    pressed = []
    stages = []

    async def fake_open_contact_search(agent, service, client):
        return True

    async def fake_emit(agent, service, stage, detail):
        stages.append((stage, detail))

    async def fake_hotkey(agent, service, client, keys):
        return None

    async def fake_type(agent, service, client, text):
        typed.append(text)

    async def fake_press(agent, service, client, key):
        pressed.append(key)

    async def fake_focus(*args, **kwargs):
        return "Discord"

    monkeypatch.setattr(ms, "open_contact_search", fake_open_contact_search)
    monkeypatch.setattr(ms, "emit_messaging_stage", fake_emit)
    monkeypatch.setattr(ms, "service_hotkey", fake_hotkey)
    monkeypatch.setattr(ms, "type_service_text", fake_type)
    monkeypatch.setattr(ms, "service_press", fake_press)
    monkeypatch.setattr(ms, "force_service_keyboard_focus", fake_focus)

    class Tools:
        async def execute(self, call, confirmed=False):
            return SimpleNamespace(success=True, data={})

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(tools=Tools())
    result = await session._resolve_messaging_contact("discord", "EpicHMK", {"mode": "desktop"})

    assert typed == ["EpicHMK"]
    assert pressed == ["enter"]
    assert result["opened"] == "EpicHMK"
    assert any(stage == "open_matching_result" for stage, _ in stages)


@pytest.mark.asyncio
async def test_discord_recipient_selection_never_uses_click_coordinates(monkeypatch):
    pressed = []

    async def fake_foreground(*args, **kwargs):
        return "Discord"

    async def fake_description(agent, prompt):
        return SimpleNamespace(description="USER | EpicHMK | epichmk")

    async def fake_press(agent, service, client, key):
        pressed.append(key)

    async def noop(*args, **kwargs):
        return None

    class Tools:
        async def execute(self, call, confirmed=False):
            return SimpleNamespace(success=True, data={})

    monkeypatch.setattr(ms, "ensure_service_foreground", fake_foreground)
    monkeypatch.setattr(ms, "observe_messaging_description", fake_description)
    monkeypatch.setattr(ms, "service_press", fake_press)
    monkeypatch.setattr(ms, "emit_messaging_stage", noop)

    agent = SimpleNamespace(tools=Tools())
    await ms.open_matching_discord_recipient(agent, {"mode": "desktop"}, "EpicHMK")
    assert pressed == ["enter"]

    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def open_matching_discord_recipient"):source.index("async def open_contact_search")]
    assert "click_service_element" not in block
    assert "element.center" not in block


def test_discord_console_keeps_only_important_stage_checkpoints():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert 'visible_discord_stages' in source
    assert '"recipient_search"' in source
    assert '"open_matching_result"' in source
    assert '"chat_verified"' in source
    assert '"focus_verified"' not in source[source.index("visible_discord_stages"):source.index("if concise", source.index("visible_discord_stages"))]


@pytest.mark.asyncio
async def test_discord_filtered_user_match_does_not_reclassify_rows(monkeypatch):
    prompts = []
    pressed = []

    async def fake_foreground(*args, **kwargs):
        return "Discord"

    async def fake_description(agent, prompt):
        prompts.append(prompt)
        return SimpleNamespace(description="USER | EpicHMK | epichmk")

    async def fake_press(agent, service, client, key):
        pressed.append(key)

    async def noop(*args, **kwargs):
        return None

    class Tools:
        async def execute(self, call, confirmed=False):
            return SimpleNamespace(success=True, data={})

    monkeypatch.setattr(ms, "ensure_service_foreground", fake_foreground)
    monkeypatch.setattr(ms, "observe_messaging_description", fake_description)
    monkeypatch.setattr(ms, "service_press", fake_press)
    monkeypatch.setattr(ms, "emit_messaging_stage", noop)

    agent = SimpleNamespace(tools=Tools())
    await ms.open_matching_discord_recipient(agent, {"mode": "desktop"}, "EpicHMK")

    assert pressed == ["enter"]
    assert prompts
    prompt = prompts[0]
    assert "Read the selectable USER result rows" in prompt
    assert "Do not decide which" in prompt and "account Conduit should open" in prompt
    assert "USER | <display name> | <username>" in prompt
