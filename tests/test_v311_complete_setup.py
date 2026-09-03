
from pathlib import Path

def test_chromium_is_mandatory_and_verified():
    root = Path(__file__).resolve().parents[1]
    setup = (root/"setup.py").read_text(encoding="utf-8")
    env = (root/"conduit/environment/service.py").read_text(encoding="utf-8")
    assert '"playwright", "install", "chromium"' in setup
    assert "Install Playwright Chromium browser" in setup
    assert "required=False" not in setup
    assert "p.chromium.executable_path" in env

def test_tesseract_is_mandatory_native_dependency():
    root = Path(__file__).resolve().parents[1]
    setup = (root/"setup.py").read_text(encoding="utf-8")
    env = (root/"conduit/environment/service.py").read_text(encoding="utf-8")
    assert "UB-Mannheim.TesseractOCR" in setup
    assert "install_tesseract()" in setup
    assert "verify_tesseract" in env

def test_ocr_and_transcription_are_core_dependencies():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root/"pyproject.toml").read_text(encoding="utf-8")
    required = pyproject.split("[project.optional-dependencies]")[0]
    assert '"pytesseract>=0.3.13"' in required
    assert '"faster-whisper>=1.1.0"' in required

def test_setup_still_keeps_compatibility_extra():
    root = Path(__file__).resolve().parents[1]
    setup = (root/"setup.py").read_text(encoding="utf-8")
    assert 'pip", "install", "-e", ".[file_processing_extra]"' in setup

def test_version_311():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
