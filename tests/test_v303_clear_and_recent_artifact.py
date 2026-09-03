
from pathlib import Path
from types import SimpleNamespace

from conduit.conversation.session import ConversationSession
from conduit.conversation.command_aliases import normalize_conversation_command


def test_natural_clear_maps_to_slash_clear():
    assert normalize_conversation_command("clear short term memory") == "/clear"
    assert normalize_conversation_command("clear conversation memory") == "/clear"


def test_vscode_pronoun_detector():
    assert ConversationSession._is_open_recent_artifact_in_vscode("open that in vs code")
    assert ConversationSession._is_open_recent_artifact_in_vscode("open it in Visual Studio Code")
    assert not ConversationSession._is_open_recent_artifact_in_vscode("open this project in vs code")


def test_latest_artifact_uses_session_file_context(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    target = tmp_path / "memory_test.py"
    target.write_text("print('ok')", encoding="utf-8")

    session = object.__new__(ConversationSession)
    session._file_context = {"last_artifact_path": str(target)}
    session.session_memory = SimpleNamespace(recent_turns=lambda n: [])
    monkeypatch.setattr(session_mod.file_service, "get_active_file", lambda: None)

    assert session._latest_artifact_path() == target.resolve()


def test_open_recent_artifact_uses_latest_file_not_dev_project(tmp_path, monkeypatch):
    target = tmp_path / "memory_test.py"
    target.write_text("print('ok')", encoding="utf-8")
    session = object.__new__(ConversationSession)
    session._latest_artifact_path = lambda: target
    session._vscode_executable = lambda: "code.cmd"

    launched = []
    from conduit.conversation import session as session_mod
    monkeypatch.setattr(
        session_mod.subprocess,
        "Popen",
        lambda argv, **kwargs: launched.append((argv, kwargs)) or SimpleNamespace(),
    )

    answer, report = session._open_recent_artifact_in_vscode()
    assert report.success is True
    assert "memory_test.py" in answer
    assert launched[0][0] == ["code.cmd", str(target)]


def test_runtime_direct_commands_restore_busy_state_in_source():
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "def _finish_direct_command" in source
    assert "self.signals.busy.emit(False)" in source
    assert '_finish_direct_command(command, "Conversation context cleared."' in source


def test_gui_answer_always_reenables_prompt_in_source():
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit/gui/app.py").read_text(encoding="utf-8")
    start = source.index("def _runtime_answer")
    block = source[start:start + 1200]
    assert "self.command_input.setEnabled(True)" in block
    assert "self.send_button.setEnabled(True)" in block
    assert "self.command_input.setFocus()" in block


def test_version_303():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
