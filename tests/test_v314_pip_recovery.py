
from pathlib import Path

def source():
    root = Path(__file__).resolve().parents[1]
    return (root/"setup.py").read_text(encoding="utf-8")

def test_venv_creation_does_not_depend_on_ensurepip():
    text = source()
    assert '"venv", "--without-pip"' in text

def test_ensurepip_failure_is_nonfatal_recovery_step():
    text = source()
    assert "try_run(" in text
    assert '"ensurepip", "--upgrade", "--default-pip"' in text

def test_base_python_pip_can_manage_target_venv():
    text = source()
    assert '"--python"' in text
    assert '"Install pip into Conduit venv from compatible base Python"' in text

def test_get_pip_is_final_fallback():
    text = source()
    assert "https://bootstrap.pypa.io/get-pip.py" in text
    assert "def _bootstrap_pip_with_get_pip()" in text

def test_version_314():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
