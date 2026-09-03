
from pathlib import Path
import inspect

from conduit.browser import sessions as bs
from conduit.browser.engine import BrowserEngine


def test_focus_restores_only_when_minimized():
    source = inspect.getsource(bs._force_foreground_window)
    assert "IsIconic" in source
    assert "SW_RESTORE only for minimized windows" in source
    # The focus path itself must not maximize/resize a normal browser.
    assert "SW_MAXIMIZE" not in source
    assert "ShowWindow(hwnd, 3)" not in source


def test_existing_browser_discovery_uses_executable_not_title_guess():
    source = inspect.getsource(bs.browser_windows_by_executable)
    assert "_process_executable_path" in source
    assert "expected_norm" in source
    assert "actual_norm" in source


def test_browser_engine_no_longer_forces_maximize_on_real_profile():
    source = inspect.getsource(BrowserEngine.activate_real_profile)
    assert "maximize_native_session" not in source
    source2 = inspect.getsource(BrowserEngine.use_default_profile)
    assert "maximize_native_session" not in source2


def test_project_version_is_219():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
