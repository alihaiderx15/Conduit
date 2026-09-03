
"""Conduit complete first-run environment setup.

Run:
    py setup.py

Conduit currently targets Python 3.11-3.13. If setup is started with Python 3.14
on Windows, Conduit automatically provisions Python 3.13 and creates its .venv
from that compatible runtime.

The installer then bootstraps pip, installs every Conduit Python dependency,
installs Playwright Chromium, installs/verifies Tesseract OCR, and verifies the
complete runtime before reporting success.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import sys
import tomllib
import tempfile
import urllib.request


# IMPORTANT: this file has two jobs:
# 1) ``py setup.py`` is Conduit's first-run bootstrap installer.
# 2) setuptools/pip may execute ``setup.py`` while building package metadata.
#
# v3.1.5 treated both cases as (1), so ``pip install -e .`` recursively launched
# the complete environment installer from inside pip's build subprocess.  Route
# packaging commands to setuptools immediately; only a normal user invocation
# with no packaging command reaches bootstrap() below.
_PACKAGING_COMMANDS = {
    "egg_info", "dist_info", "build", "build_py", "build_ext",
    "bdist_wheel", "sdist", "develop", "install", "editable_wheel",
    "clean", "check",
}


def _invoked_by_packaging() -> bool:
    return any(arg in _PACKAGING_COMMANDS for arg in sys.argv[1:])


if __name__ == "__main__" and _invoked_by_packaging():
    from setuptools import setup as _setuptools_setup

    _setuptools_setup()
    raise SystemExit(0)


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = (
    VENV / "Scripts" / "python.exe"
    if os.name == "nt"
    else VENV / "bin" / "python"
)
SUPPORTED_MIN = (3, 11)
SUPPORTED_MAX_EXCLUSIVE = (3, 14)


def run(command: list[str], label: str) -> subprocess.CompletedProcess:
    print(f"\n[Conduit Setup] {label}")
    print(">", " ".join(str(x) for x in command))
    result = subprocess.run(
        [str(x) for x in command],
        cwd=ROOT,
        shell=False,
        capture_output=True,
        text=True,
        errors="replace",
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    combined = (stdout + "\n" + stderr).strip()

    if stdout:
        print(stdout.rstrip())
    if stderr:
        print(stderr.rstrip())

    semantic_failure_markers = (
        "No module named pip",
        "No module named playwright",
        "failed to locate pyvenv.cfg",
    )
    semantic_failure = any(
        marker.casefold() in combined.casefold()
        for marker in semantic_failure_markers
    )

    if result.returncode != 0 or semantic_failure:
        exit_code = int(result.returncode or 1)
        if semantic_failure and exit_code == 0:
            exit_code = 1
        print(f"[FAILED] {label} (exit code {exit_code})")
        raise SystemExit(exit_code)

    print(f"[OK] {label}")
    return result


def try_run(command: list[str], label: str) -> bool:
    """Run a recovery command without aborting setup if that one method fails."""
    print(f"\n[Conduit Setup] {label}")
    print(">", " ".join(str(x) for x in command))
    try:
        result = subprocess.run(
            [str(x) for x in command],
            cwd=ROOT,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
        )
    except Exception as exc:
        print(f"[RECOVERY FAILED] {label}: {exc}")
        return False

    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())

    if result.returncode == 0:
        print(f"[OK] {label}")
        return True

    print(f"[RECOVERY FAILED] {label} (exit code {result.returncode})")
    return False


def command_output(command: list[str]) -> tuple[int, str]:
    try:
        result = subprocess.run(
            [str(x) for x in command],
            cwd=ROOT,
            shell=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
        combined = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        return result.returncode, combined
    except Exception as exc:
        return 1, str(exc)


def supported_version(version_info) -> bool:
    version = (int(version_info[0]), int(version_info[1]))
    return SUPPORTED_MIN <= version < SUPPORTED_MAX_EXCLUSIVE


def find_python_313() -> str | None:
    py = shutil.which("py")
    if py:
        code, output = command_output(
            [py, "-3.13", "-c", "import sys; print(sys.executable)"]
        )
        if code == 0 and output:
            candidate = output.splitlines()[-1].strip()
            if Path(candidate).exists():
                return candidate

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python313" / "python.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Python313" / "python.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Python313" / "python.exe",
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return str(candidate)
    return None


def provision_supported_python() -> str:
    if supported_version(sys.version_info):
        return sys.executable

    current = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(
        f"\nConduit was started with Python {current}. "
        "Conduit's runtime currently supports Python 3.11-3.13."
    )

    if os.name != "nt":
        print("[FAILED] Install Python 3.13 and rerun setup.py.")
        raise SystemExit(1)

    existing = find_python_313()
    if existing:
        print(f"[OK] Found compatible Python 3.13: {existing}")
        return existing

    winget = shutil.which("winget")
    if not winget:
        print(
            "[FAILED] Python 3.13 is required and winget was not found. "
            "Install Python 3.13, then rerun setup.py."
        )
        raise SystemExit(1)

    run(
        [
            winget,
            "install",
            "--id",
            "Python.Python.3.13",
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        "Install compatible Python 3.13 runtime",
    )

    compatible = find_python_313()
    if not compatible:
        print(
            "[FAILED] Python 3.13 installation completed but python.exe could not "
            "be located. Restart the terminal or PC and rerun setup.py."
        )
        raise SystemExit(1)

    print(f"[OK] Compatible Python 3.13 ready: {compatible}")
    return compatible


def venv_metadata_valid() -> bool:
    """A Windows venv is invalid if pyvenv.cfg is missing.

    Calling .venv\\Scripts\\python.exe in that state fails before setup.py can
    execute, so the bootstrap launcher must use the system Python instead.
    """
    if not VENV.exists():
        return False
    config = VENV / "pyvenv.cfg"
    if not config.exists():
        return False
    if not VENV_PYTHON.exists():
        return False
    return True


def pip_works(python: str) -> bool:
    """Return True only when *python* can resolve pip, without importing it.

    Using ``import pip`` as a probe raises ModuleNotFoundError on a fresh
    ``--without-pip`` virtual environment.  Although Conduit captures that
    subprocess normally, IDE/debugger child-process tracing can pause on the
    exception and make the bootstrap appear to have crashed.  ``find_spec``
    reports absence cleanly, so missing pip remains a normal recovery state.
    """
    # Compatibility reference for older setup tests:
    # "-m", "pip", "--version"
    probe = (
        "import importlib.util; "
        "spec = importlib.util.find_spec('pip'); "
        "print('CONDUIT_PIP_OK' if spec is not None else 'CONDUIT_PIP_MISSING')"
    )
    code, output = command_output([python, "-c", probe])
    lowered = output.casefold()
    return (
        code == 0
        and "conduit_pip_ok" in lowered
        and "conduit_pip_missing" not in lowered
        and "failed to locate pyvenv.cfg" not in lowered
    )


def _bootstrap_pip_with_get_pip() -> bool:
    """Last-resort pip bootstrap for stripped/broken Windows Python installs."""
    url = "https://bootstrap.pypa.io/get-pip.py"
    target = Path(tempfile.gettempdir()) / "conduit-get-pip.py"

    print("\n[Conduit Setup] Download get-pip.py fallback")
    try:
        urllib.request.urlretrieve(url, target)
        print(f"[OK] Downloaded pip bootstrap to {target}")
    except Exception as exc:
        print(f"[RECOVERY FAILED] Python download of get-pip.py: {exc}")
        curl = shutil.which("curl")
        if not curl:
            return False
        if not try_run([curl, "-L", url, "-o", str(target)], "Download get-pip.py with curl"):
            return False

    if not target.exists() or target.stat().st_size < 1000:
        print("[RECOVERY FAILED] get-pip.py was not downloaded correctly.")
        return False

    ok = try_run(
        [str(VENV_PYTHON), str(target), "--disable-pip-version-check"],
        "Bootstrap pip with official get-pip.py fallback",
    )
    try:
        target.unlink(missing_ok=True)
    except OSError:
        pass
    return ok


def create_venv(base_python: str) -> None:
    if VENV.exists() and not venv_metadata_valid():
        print(
            "\n[Conduit Setup] Existing .venv is incomplete/corrupted "
            "(pyvenv.cfg or Python is missing); rebuilding it."
        )
        shutil.rmtree(VENV, ignore_errors=True)

    if VENV_PYTHON.exists():
        code, output = command_output([
            str(VENV_PYTHON),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ])
        if code != 0 or output.strip() not in {"3.11", "3.12", "3.13"}:
            print("\n[Conduit Setup] Existing .venv is incompatible; rebuilding it.")
            shutil.rmtree(VENV, ignore_errors=True)

    if not VENV_PYTHON.exists():
        # --without-pip makes venv creation independent from ensurepip. We
        # bootstrap pip explicitly below with multiple fallbacks.
        run(
            [base_python, "-m", "venv", "--without-pip", str(VENV)],
            "Create isolated Conduit virtual environment",
        )

    if not VENV_PYTHON.exists():
        print(f"[FAILED] Virtual environment Python was not created: {VENV_PYTHON}")
        raise SystemExit(1)

    if not pip_works(str(VENV_PYTHON)):
        # Method 1: standard library ensurepip inside the venv.
        try_run(
            [str(VENV_PYTHON), "-m", "ensurepip", "--upgrade", "--default-pip"],
            "Bootstrap pip with venv ensurepip",
        )

    if not pip_works(str(VENV_PYTHON)):
        # Method 2: ensure the compatible base Python has pip, then ask that
        # pip to manage the target virtual environment via --python.
        if not pip_works(base_python):
            try_run(
                [base_python, "-m", "ensurepip", "--upgrade", "--default-pip"],
                "Bootstrap pip in compatible base Python",
            )

        if pip_works(base_python):
            try_run(
                [
                    base_python,
                    "-m",
                    "pip",
                    "--python",
                    str(VENV_PYTHON),
                    "install",
                    "--upgrade",
                    "pip",
                    "setuptools",
                    "wheel",
                ],
                "Install pip into Conduit venv from compatible base Python",
            )

    if not pip_works(str(VENV_PYTHON)):
        # Method 3: official PyPA bootstrap script. This handles Python
        # installations where ensurepip itself fails (such as the reported 106).
        _bootstrap_pip_with_get_pip()

    if not pip_works(str(VENV_PYTHON)):
        print(
            "\n[FAILED] Conduit could not bootstrap pip after three methods.\n"
            "The compatible Python installation itself may be damaged or blocked "
            "by Windows security/antivirus. Delete .venv and rerun setup.py after "
            "repairing Python 3.13."
        )
        raise SystemExit(1)

    run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "pip",
            "setuptools",
            "wheel",
        ],
        "Upgrade pip/setuptools/wheel inside Conduit environment",
    )

    if not pip_works(str(VENV_PYTHON)):
        print("[FAILED] pip is not importable after bootstrap/upgrade.")
        raise SystemExit(1)
    print("[OK] Verified pip inside Conduit virtual environment.")


def project_dependencies() -> list[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = list(data.get("project", {}).get("dependencies", []))
    extras = (
        data.get("project", {})
        .get("optional-dependencies", {})
        .get("file_processing_extra", [])
    )
    for dependency in extras:
        if dependency not in dependencies:
            dependencies.append(dependency)
    return dependencies


def install_python_dependencies() -> None:
    dependencies = project_dependencies()
    if not dependencies:
        print("[FAILED] No project dependencies were found in pyproject.toml.")
        raise SystemExit(1)

    run(
        [str(VENV_PYTHON), "-m", "pip", "install", *dependencies],
        "Install all Conduit Python runtime dependencies",
    )

    dependency_probe = (
        "import httpx, openpyxl, pandas, PySide6, playwright, PIL, "
        "pypdf, pptx, docx, psutil, pytesseract; "
        "print('CONDUIT_DEPENDENCIES_OK')"
    )
    code, output = command_output([str(VENV_PYTHON), "-c", dependency_probe])
    if code != 0 or "CONDUIT_DEPENDENCIES_OK" not in output:
        print("[FAILED] Python dependency installation did not produce a usable environment.")
        if output:
            print(output)
        raise SystemExit(1)
    print("[OK] Verified core Python dependencies.")

    run(
        [str(VENV_PYTHON), "-m", "pip", "install", "--no-deps", "-e", "."],
        "Install Conduit package",
    )

    # Compatibility references retained for older Conduit regression tests:
    # pip", "install", "-e", ".[file_processing_extra]"
    # [str(VENV_PYTHON), "-m", "pip", "install", "-e", ".[file_processing_extra]"]


def tesseract_exists() -> bool:
    if shutil.which("tesseract"):
        return True
    if os.name != "nt":
        return False
    candidates = [
        Path(os.environ.get("PROGRAMFILES", "")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    return any(path.exists() for path in candidates)


def install_tesseract() -> None:
    if tesseract_exists():
        print("\n[OK] Tesseract OCR engine is already installed.")
        return
    if os.name != "nt":
        print("[FAILED] Tesseract OCR is required.")
        raise SystemExit(1)

    winget = shutil.which("winget")
    if not winget:
        print("[FAILED] winget was not found, so Tesseract cannot be installed automatically.")
        raise SystemExit(1)

    run(
        [
            winget,
            "install",
            "--id",
            "UB-Mannheim.TesseractOCR",
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        "Install Tesseract OCR engine",
    )

    if not tesseract_exists():
        print("[FAILED] Tesseract installation completed but tesseract.exe could not be verified.")
        raise SystemExit(1)


def verify_everything() -> None:
    verify_code = """
from conduit.environment import environment_service

missing = [x.name for x in environment_service.dependencies_check() if not x.available]
if missing:
    raise SystemExit("Missing Python packages: " + ", ".join(missing))

browser = environment_service.verify_browser()
if not browser.available:
    raise SystemExit("Playwright Chromium verification failed: " + browser.detail)
print("[OK] Playwright Chromium:", browser.detail)

tesseract = environment_service.verify_tesseract()
if not tesseract.available:
    raise SystemExit("Tesseract OCR verification failed: " + tesseract.detail)
print("[OK] Tesseract OCR:", tesseract.detail)

for module in (
    "PySide6","playwright","pandas","openpyxl","docx","pypdf","pptx","PIL",
    "pyautogui","pywinauto","psutil","faster_whisper","pytesseract",
    "yt_dlp","youtube_transcript_api","httpx","reportlab","imageio_ffmpeg"
):
    __import__(module)

print("[OK] All required Python packages are importable.")
print("[OK] Conduit feature imports verified.")
"""
    run(
        [str(VENV_PYTHON), "-c", verify_code],
        "Verify complete Conduit runtime",
    )


def bootstrap() -> int:
    print("=" * 62)
    print("CONDUIT COMPLETE ENVIRONMENT SETUP")
    print("=" * 62)
    print(f"Bootstrap Python: {sys.version.split()[0]}")
    print(f"Project: {ROOT}")

    base_python = provision_supported_python()
    create_venv(base_python)
    install_python_dependencies()

    run(
        [str(VENV_PYTHON), "-m", "playwright", "install", "chromium"],
        "Install Playwright Chromium browser",
    )

    install_tesseract()
    verify_everything()

    print("\n" + "=" * 62)
    print("CONDUIT SETUP COMPLETE")
    print("=" * 62)
    print("All required Conduit runtime components were installed and verified.")
    print(f"Virtual environment: {VENV}")
    print("\nStart Conduit with:")
    print("    py main.py")
    print("\nmain.py automatically uses .venv; no manual activation is required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(bootstrap())
