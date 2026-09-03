
from pathlib import Path

def test_python_314_is_not_used_for_conduit_runtime():
    root=Path(__file__).resolve().parents[1]
    source=(root/"setup.py").read_text(encoding="utf-8")
    assert "SUPPORTED_MAX_EXCLUSIVE = (3, 14)" in source
    assert "Python.Python.3.13" in source
    assert "find_python_313" in source

def test_dependencies_are_installed_explicitly():
    root=Path(__file__).resolve().parents[1]
    source=(root/"setup.py").read_text(encoding="utf-8")
    assert "def project_dependencies()" in source
    assert '"pip", "install", *dependencies' in source
    assert '"--no-deps", "-e", "."' in source

def test_pyproject_caps_python_before_314():
    root=Path(__file__).resolve().parents[1]
    source=(root/"pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11,<3.14"' in source

def test_version_313():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
