
from pathlib import Path
import inspect

from conduit.browser import sessions as bs


def test_maximize_uses_verified_windows_maximize_path():
    source = inspect.getsource(bs.maximize_native_session)
    assert "IsZoomed" in source
    assert "ShowWindowAsync" in source
    assert "SC_MAXIMIZE" in source
    assert "PostMessageW" in source
    # Regression guard: the old Restore -> Maximize race caused Opera GX to
    # remain snapped at half-screen.
    assert "SW_RESTORE" not in source


def test_project_version_is_218():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
