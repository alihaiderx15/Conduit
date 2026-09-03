
from pathlib import Path


def _root():
    return Path(__file__).resolve().parents[1]


def test_gui_launcher_exists_and_uses_v250():
    root=_root()
    source=(root/"scripts/conduit_gui.py").read_text(encoding="utf-8")
    assert "run_gui(" in source
    assert 'version="3.1.8"' in source


def test_gui_drop_is_connected_to_existing_file_processing_backend():
    root=_root()
    app=(root/"conduit/gui/app.py").read_text(encoding="utf-8")
    runtime=(root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "self.runtime.register_dropped_file" in app
    assert "self.conversation.register_gui_dropped_file(path)" in runtime


def test_chat_and_programmer_console_are_separate_surfaces():
    root=_root()
    app=(root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert "class ChatView" in app
    assert "class ConsoleView" in app
    assert 'Panel("Chat Interface")' in app
    assert 'Panel("System Console")' in app


def test_gui_commands_use_real_conversation_session():
    root=_root()
    runtime=(root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "ConversationSession(self.agent" in runtime
    assert "self.conversation.ask(command)" in runtime
    assert "confirm_pending_message" in runtime


def test_interrupt_is_connected_to_conversation_interrupt():
    root=_root()
    app=(root/"conduit/gui/app.py").read_text(encoding="utf-8")
    runtime=(root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "Qt.Key_Escape" in app
    assert "self.runtime.interrupt()" in app
    assert "self.conversation.interrupt()" in runtime


def test_gui_theme_uses_requested_three_accent_colors():
    root=_root()
    theme=(root/"conduit/gui/theme.py").read_text(encoding="utf-8")
    assert 'BLUE = "#168BFF"' in theme
    assert 'PURPLE = "#A84DFF"' in theme
    assert 'YELLOW = "#FFD21A"' in theme


def test_gui_dependencies_are_declared():
    root=_root()
    project=(root/"pyproject.toml").read_text(encoding="utf-8")
    assert '"PySide6>=6.8.0"' in project
    assert '"psutil>=6.0.0"' in project


def test_version_250():
    root=_root()
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
