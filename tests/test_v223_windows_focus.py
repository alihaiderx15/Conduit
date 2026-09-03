
from pathlib import Path
import inspect
from conduit.browser import sessions as bs

def test_force_foreground_uses_thread_input():
    source = inspect.getsource(bs._force_foreground_window)
    assert "AttachThreadInput" in source
    assert "SetForegroundWindow" in source
    assert "keybd_event" in source
    assert "IsIconic" in source

def test_focus_session_delegates_without_resize():
    source = inspect.getsource(bs.focus_native_session)
    assert "_force_foreground_window" in source
    assert "SW_MAXIMIZE" not in source

def test_version_223():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
