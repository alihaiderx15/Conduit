
from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys


@dataclass(slots=True)
class EnvironmentCheck:
    name: str
    available: bool
    detail: str = ""

    def data(self):
        return asdict(self)


class EnvironmentService:
    """Checks and installs Conduit runtime prerequisites without AI guessing."""

    REQUIRED_IMPORTS = {
        "httpx": "httpx",
        "Pillow": "PIL",
        "imageio-ffmpeg": "imageio_ffmpeg",
        "python-pptx": "pptx",
        "openpyxl": "openpyxl",
        "pandas": "pandas",
        "python-docx": "docx",
        "pypdf": "pypdf",
        "reportlab": "reportlab",
        "PyAutoGUI": "pyautogui",
        "PySide6": "PySide6",
        "psutil": "psutil",
        "pywinauto": "pywinauto",
        "pycaw": "pycaw",
        "playwright": "playwright",
        "yt-dlp": "yt_dlp",
        "youtube-transcript-api": "youtube_transcript_api",
        "google-genai": "google.genai",
        "pytesseract": "pytesseract",
        "faster-whisper": "faster_whisper",
    }

    OPTIONAL_FEATURES = {
        "ocr": ["pytesseract>=0.3.13"],
        "local_transcription": ["faster-whisper>=1.1.0"],
    }

    RECOMMENDED_OLLAMA_MODELS = (
        ("qwen2.5vl:7b", "Vision • Desktop • Images"),
        ("qwen2.5-coder:7b", "Coding • Lightweight"),
    )

    @staticmethod
    def python_check() -> EnvironmentCheck:
        ok = sys.version_info >= (3, 11)
        return EnvironmentCheck(
            "python",
            ok,
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )

    @classmethod
    def dependencies_check(cls) -> list[EnvironmentCheck]:
        rows = []
        for package, module in cls.REQUIRED_IMPORTS.items():
            try:
                found = importlib.util.find_spec(module) is not None
            except (ModuleNotFoundError, ValueError):
                found = False
            rows.append(EnvironmentCheck(package, found, "installed" if found else "missing"))
        return rows

    @staticmethod
    def verify_ollama() -> EnvironmentCheck:
        exe = shutil.which("ollama")
        if exe:
            return EnvironmentCheck("ollama", True, exe)
        # Common Windows installation location.
        local = Path(os.environ.get("LOCALAPPDATA", ""))/"Programs"/"Ollama"/"ollama.exe"
        if local.exists():
            return EnvironmentCheck("ollama", True, str(local))
        return EnvironmentCheck("ollama", False, "Ollama is not installed or is not on PATH.")

    @staticmethod
    def ollama_executable() -> str | None:
        hit = shutil.which("ollama")
        if hit:
            return hit
        local = Path(os.environ.get("LOCALAPPDATA", ""))/"Programs"/"Ollama"/"ollama.exe"
        return str(local) if local.exists() else None

    @classmethod
    def verify_model(cls, model: str) -> EnvironmentCheck:
        exe = cls.ollama_executable()
        if not exe:
            return EnvironmentCheck(model, False, "Ollama is not installed.")
        try:
            result = subprocess.run(
                [exe, "list"],
                shell=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
            )
            names = []
            for line in result.stdout.splitlines()[1:]:
                if line.strip():
                    names.append(line.split()[0])
            found = any(x.casefold() == model.casefold() for x in names)
            return EnvironmentCheck(
                model,
                found,
                "installed" if found else "model is not installed",
            )
        except Exception as exc:
            return EnvironmentCheck(model, False, f"Could not inspect Ollama models: {exc}")

    @staticmethod
    def verify_tesseract() -> EnvironmentCheck:
        exe = shutil.which("tesseract")
        if exe:
            return EnvironmentCheck("tesseract", True, exe)
        if os.name == "nt":
            candidates = [
                Path(os.environ.get("PROGRAMFILES", ""))/"Tesseract-OCR"/"tesseract.exe",
                Path(os.environ.get("LOCALAPPDATA", ""))/"Programs"/"Tesseract-OCR"/"tesseract.exe",
            ]
            for candidate in candidates:
                if str(candidate) and candidate.exists():
                    return EnvironmentCheck("tesseract", True, str(candidate))
        return EnvironmentCheck(
            "tesseract",
            False,
            "Tesseract OCR engine is not installed or is not on PATH.",
        )

    @staticmethod
    def verify_browser() -> EnvironmentCheck:
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            return EnvironmentCheck("browser", False, "Playwright Python package is missing.")

        try:
            with sync_playwright() as p:
                executable = Path(p.chromium.executable_path)
                if executable.exists():
                    return EnvironmentCheck("browser", True, str(executable))
                return EnvironmentCheck(
                    "browser",
                    False,
                    f"Playwright Chromium executable is missing: {executable}",
                )
        except Exception as exc:
            return EnvironmentCheck(
                "browser",
                False,
                f"Playwright Chromium verification failed: {exc}",
            )

    @staticmethod
    def install_optional_feature(feature: str) -> tuple[bool, str]:
        packages = EnvironmentService.OPTIONAL_FEATURES.get(str(feature).casefold().strip())
        if not packages:
            return False, f"Unknown optional feature: {feature}"
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *packages],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode == 0:
            return True, f"Installed optional feature {feature}."
        return False, (result.stderr or result.stdout).strip()

    @staticmethod
    def install_playwright_chromium() -> tuple[bool, str]:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
        if result.returncode == 0:
            return True, "Playwright Chromium installed."
        return False, (result.stderr or result.stdout).strip()

    @staticmethod
    def start_ollama_installer() -> tuple[bool, str]:
        if os.name != "nt":
            return False, "Automatic Ollama installation is currently implemented for Windows."
        command = "irm https://ollama.com/install.ps1 | iex"
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoExit",
                    "-ExecutionPolicy", "Bypass",
                    "-Command", command,
                ],
                shell=False,
                creationflags=creationflags,
            )
            return True, "Opened PowerShell and started the official Ollama installer."
        except Exception as exc:
            return False, f"Could not start the Ollama installer: {exc}"

    @classmethod
    def start_model_download(cls, model: str) -> tuple[bool, str]:
        exe = cls.ollama_executable()
        if not exe:
            return False, "Ollama is not installed."
        if os.name != "nt":
            return False, "Visible Ollama model downloads are currently implemented for Windows."
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            subprocess.Popen(
                ["cmd.exe", "/k", exe, "pull", str(model)],
                shell=False,
                creationflags=creationflags,
            )
            return True, f"Opened Command Prompt and started: ollama pull {model}"
        except Exception as exc:
            return False, f"Could not start model download: {exc}"

    @classmethod
    def check_all(cls) -> dict:
        return {
            "python": cls.python_check().data(),
            "dependencies": [x.data() for x in cls.dependencies_check()],
            "browser": cls.verify_browser().data(),
            "tesseract": cls.verify_tesseract().data(),
            "ollama": cls.verify_ollama().data(),
            "recommended_models": [
                cls.verify_model(name).data()
                for name, _description in cls.RECOMMENDED_OLLAMA_MODELS
            ],
        }


environment_service = EnvironmentService()
