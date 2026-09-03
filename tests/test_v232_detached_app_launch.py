
from pathlib import Path
from types import SimpleNamespace
import subprocess

from conduit.system_control import windows as sw
from conduit.messaging import service as ms


def test_detached_launcher_redirects_all_standard_handles(monkeypatch):
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace()

    monkeypatch.setattr(sw.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sw.sys, "platform", "win32")

    sw.launch_detached_process(["Discord.exe"])

    assert calls
    command, kwargs = calls[0]
    assert command == ["Discord.exe"]
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert "creationflags" in kwargs


def test_system_open_app_uses_detached_shell_open(monkeypatch):
    monkeypatch.setattr(sw, "_require_windows", lambda: None)
    monkeypatch.setattr(
        sw,
        "resolve_app",
        lambda app: {"name": "Discord", "path": r"C:\Apps\Discord.lnk", "source": "shortcut"},
    )
    calls = []
    monkeypatch.setattr(sw, "_shell_open_detached", lambda target: calls.append(target))

    result = sw.open_app("discord")

    assert calls == [r"C:\Apps\Discord.lnk"]
    assert result["opened"] is True


def test_messaging_discord_updater_uses_detached_launcher(monkeypatch, tmp_path):
    update = tmp_path / "Update.exe"
    update.write_text("x")
    calls = []

    monkeypatch.setattr(ms.sys, "platform", "win32")
    monkeypatch.setattr(
        ms,
        "launch_detached_process",
        lambda command: calls.append(command) or SimpleNamespace(),
    )

    ok = ms.launch_installed_client(
        "discord",
        {"kind": "win32", "path": str(update)},
    )

    assert ok is True
    assert calls == [[str(update), "--processStart", "Discord.exe"]]


def test_version_232():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
