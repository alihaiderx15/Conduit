
from pathlib import Path


def test_gui_uses_available_screen_percentage_not_fixed_desktop_size():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")

    assert "available.width() * 0.82" in source
    assert "available.height() * 0.80" in source
    assert "available.width() * 0.92" in source
    assert "available.height() * 0.92" in source
    assert "screenChanged.connect" in source
    assert "HighDpiScaleFactorRoundingPolicy.PassThrough" in source
    assert "self.resize(1580, 950)" not in source
    assert "self.setMinimumSize(1180, 760)" not in source


def test_gui_centers_inside_available_desktop():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert "available.x()" in source
    assert "available.y()" in source
    assert "self.move(x, y)" in source


def test_hud_no_longer_forces_500x390_minimum():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/widgets.py").read_text(encoding="utf-8")
    assert "self.setMinimumSize(500, 390)" not in source
    assert "QSizePolicy.Expanding" in source


def test_version_251():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
