
from pathlib import Path

def test_openpyxl_requirement_uses_existing_release():
    root = Path(__file__).resolve().parents[1]
    source = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'openpyxl>=3.1.5' in source
    assert 'openpyxl>=3.1.6' not in source

def test_version_317():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root / "pyproject.toml").read_text(encoding="utf-8")
