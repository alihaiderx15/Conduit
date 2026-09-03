
from pathlib import Path

def test_setup_bootstraps_pip_in_venv():
    root=Path(__file__).resolve().parents[1]
    source=(root/"setup.py").read_text(encoding="utf-8")
    assert '"-m", "venv"' in source
    assert '"-m", "ensurepip", "--upgrade"' in source
    assert '"-m", "pip", "--version"' in source

def test_setup_uses_venv_for_dependencies_and_chromium():
    root=Path(__file__).resolve().parents[1]
    source=(root/"setup.py").read_text(encoding="utf-8")
    assert '[str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[file_processing_extra]"]' in source
    assert '[str(VENV_PYTHON), "-m", "playwright", "install", "chromium"]' in source

def test_main_auto_uses_venv():
    root=Path(__file__).resolve().parents[1]
    source=(root/"main.py").read_text(encoding="utf-8")
    assert "VENV_PYTHON" in source
    assert "Conduit has not been set up yet." in source

def test_version_312():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
