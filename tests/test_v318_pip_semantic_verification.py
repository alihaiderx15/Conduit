
from pathlib import Path

def setup_source():
    root = Path(__file__).resolve().parents[1]
    return (root/"setup.py").read_text(encoding="utf-8")

def test_pip_works_probes_pip_without_import_exception():
    source = setup_source()
    assert "importlib.util.find_spec('pip')" in source
    assert "CONDUIT_PIP_MISSING" in source
    assert '"conduit_pip_ok" in lowered' in source
    assert "import pip, sys" not in source

def test_run_rejects_missing_modules_even_if_exit_code_is_zero():
    source = setup_source()
    assert '"No module named pip"' in source
    assert '"No module named playwright"' in source
    assert "semantic_failure" in source

def test_dependencies_are_probed_before_continuing():
    source = setup_source()
    assert "CONDUIT_DEPENDENCIES_OK" in source
    assert "Verified core Python dependencies." in source

def test_version_318():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
