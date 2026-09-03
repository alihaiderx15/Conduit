from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.messaging import service as ms


@pytest.mark.asyncio
async def test_discord_desktop_readiness_uses_vision_until_ready(monkeypatch):
    class Result:
        def __init__(self, success=True, data=None):
            self.success = success
            self.data = data or {}

    class Tools:
        async def execute(self, call, confirmed=False):
            if call.name == "system.list_windows":
                return Result(True, {"windows": [{"title": "Discord", "handle": 222}]})
            if call.name == "system.active_window":
                return Result(True, {"title": "Discord", "handle": 222})
            return Result(True, {})

    calls = []

    async def classifier(agent, service):
        calls.append(("broad", service))
        return "loading", "Discord splash visible"

    async def compact_classifier(agent):
        calls.append(("compact", "discord"))
        return "ready", "normal Discord UI visible"

    async def no_sleep(_):
        return None

    monkeypatch.setattr(ms, "desktop_app_running", lambda service: True)
    monkeypatch.setattr(ms, "classify_client_state", classifier)
    monkeypatch.setattr(ms, "classify_discord_ready_compact", compact_classifier)
    import asyncio
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    agent = SimpleNamespace(router=SimpleNamespace(observer=object()), tools=Tools(), events=None)
    client = {"mode": "desktop", "window_title": "Discord", "window_handle": 222}
    state, reason, evidence = await ms.wait_until_client_ready(
        agent, "discord", client, timeout_seconds=10, poll_seconds=2
    )
    assert state == "ready"
    assert calls == [("broad", "discord"), ("compact", "discord")]
    assert evidence["attempts"] == 2


def test_discord_readiness_prompt_accepts_normal_logged_in_shell():
    source = Path(ms.__file__).read_text(encoding="utf-8")
    block = source[source.index("async def classify_client_state"):source.index("async def classify_login_state")]
    assert "For Discord specifically" in block
    assert "Do NOT require a particular DM, Home page, or chat" in block


def test_discord_major_ui_actions_use_two_second_settle_gaps():
    from conduit.conversation import session
    service_source = Path(ms.__file__).read_text(encoding="utf-8")
    search_block = service_source[service_source.index("async def open_contact_search"):]
    discord = search_block[search_block.index('if service == "discord":'):search_block.index('    await emit_messaging_stage', search_block.index('if service == "discord":'))]
    assert 'ToolCall("system.wait", {"seconds": 2.0})' in discord

    session_source = Path(session.__file__).read_text(encoding="utf-8")
    resolve = session_source[session_source.index("async def _resolve_messaging_contact"):session_source.index("async def _execute_messaging_plan")]
    assert '2.0 if service == "discord" else 1.0' in resolve
    assert resolve.count('ToolCall("system.wait", {"seconds": 2.0})') >= 2


def test_project_version_is_2051():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
