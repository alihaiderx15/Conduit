
from pathlib import Path

def test_setup_detects_missing_pyvenv_cfg():
    root = Path(__file__).resolve().parents[1]
    source = (root/"setup.py").read_text(encoding="utf-8")
    assert "def venv_metadata_valid()" in source
    assert 'VENV / "pyvenv.cfg"' in source
    assert "Existing .venv is incomplete/corrupted" in source

def test_batch_launcher_uses_system_python_not_venv():
    root = Path(__file__).resolve().parents[1]
    source = (root/"SETUP_CONDUIT.bat").read_text(encoding="utf-8")
    assert "py setup.py" in source
    assert "python setup.py" in source
    assert ".venv\\Scripts\\python.exe setup.py" not in source

def test_powershell_launcher_uses_system_python_not_venv():
    root = Path(__file__).resolve().parents[1]
    source = (root/"SETUP_CONDUIT.ps1").read_text(encoding="utf-8")
    assert "& py setup.py" in source
    assert "& python setup.py" in source

def test_version_315():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
