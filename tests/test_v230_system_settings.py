from __future__ import annotations

from pathlib import Path
import inspect
import pytest

from conduit.tools.builtin import registry
from conduit.tools.models import ToolRisk, ToolResult
from conduit.conversation import ConversationSession
from conduit.system_control import windows as win


EXPECTED_TOOLS = {
    "system.apps_installed",
    "system.app_status",
    "system.open_app",
    "system.open_apps",
    "system.close_app",
    "system.close_apps",
    "system.volume_get",
    "system.volume_set",
    "system.volume_up",
    "system.volume_down",
    "system.mute",
    "system.brightness_get",
    "system.brightness_set",
    "system.brightness_up",
    "system.brightness_down",
    "system.wifi_status",
    "system.wifi_toggle",
    "system.dark_mode_get",
    "system.dark_mode",
    "system.lock",
    "system.restart",
    "system.shutdown",
    "system.sleep_display",
    "system.open_settings",
    "system.open_task_manager",
    "system.show_desktop",
    "system.snap_window",
    "system.switch_windows",
    "system.browser_zoom",
    "system.browser_tab_shortcut",
    "system.page_navigation",
}


def test_all_structured_system_tools_are_registered():
    names = {item.name for item in registry.all()}
    assert EXPECTED_TOOLS <= names


def test_restart_and_shutdown_require_confirmation():
    assert registry.get("system.restart").risk is ToolRisk.CONFIRM
    assert registry.get("system.shutdown").risk is ToolRisk.CONFIRM


def test_generic_app_resolver_prefers_exact_discovered_name(monkeypatch):
    monkeypatch.setattr(win, "_require_windows", lambda: None)
    monkeypatch.setattr(win, "installed_apps", lambda: [
        {"name": "Spotify", "appid": "SpotifyAB.SpotifyMusic_xyz!Spotify", "source": "start_app"},
        {"name": "Steam", "path": r"C:\Users\User\Desktop\Steam.lnk", "source": "shortcut"},
    ])
    monkeypatch.setattr(win.shutil, "which", lambda _: None)
    monkeypatch.setattr(win.Path, "exists", lambda self: False)

    assert win.resolve_app("spotify")["name"] == "Spotify"
    assert win.resolve_app("steam")["name"] == "Steam"


def test_close_app_reports_already_closed(monkeypatch):
    monkeypatch.setattr(win, "_require_windows", lambda: None)
    monkeypatch.setattr(win, "find_running_app", lambda _: [])
    data = win.close_app("Discord")
    assert data["was_running"] is False
    assert data["closed"] is False
    assert "not open" in data["message"].lower()


class FakeTools:
    def __init__(self):
        self.calls = []

    async def execute(self, call, *, confirmed=False):
        self.calls.append((call.name, dict(call.arguments), confirmed))
        if call.name == "system.open_apps":
            return ToolResult(True, "Opened Discord, WhatsApp.", {"opened": []})
        if call.name == "system.close_apps":
            return ToolResult(True, "Closed Opera GX. Closed Discord.", {"results": []})
        if call.name == "system.volume_set":
            return ToolResult(True, "Set system volume to 35%.", {"volume": 35})
        return ToolResult(True, "ok", {})


class FakeLoop:
    provider = None
    model = "fake"


class FakeAgent:
    def __init__(self):
        self.tools = FakeTools()
        self.loop = FakeLoop()
        self.events = None


@pytest.mark.asyncio
async def test_multiple_apps_open_directly_without_ai_planner():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, report = await session.ask("open discord and whatsapp")
    assert agent.tools.calls == [
        ("system.open_apps", {"apps": ["discord", "whatsapp"]}, True)
    ]
    assert report.status.value == "system_action"


@pytest.mark.asyncio
async def test_multiple_apps_close_directly_without_ai_planner():
    agent = FakeAgent()
    session = ConversationSession(agent)
    await session.ask("close opera gx and discord")
    assert agent.tools.calls == [
        ("system.close_apps", {"apps": ["opera gx", "discord"]}, True)
    ]


@pytest.mark.asyncio
async def test_volume_set_is_deterministic():
    agent = FakeAgent()
    session = ConversationSession(agent)
    answer, _ = await session.ask("set volume to 35")
    assert agent.tools.calls == [
        ("system.volume_set", {"value": 35}, True)
    ]
    assert "35%" in answer


def test_memory_integration_records_system_tool_outcomes():
    from conduit.general_pc import agent as module
    source = inspect.getsource(module.GeneralPCAgent.create)
    assert 'events.subscribe("tool.completed", remember_system_tool_event)' in source
    assert '"last_opened_app"' in source
    assert '"last_closed_app"' in source
    assert '"last_system_action"' in source


def test_project_version_230():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
