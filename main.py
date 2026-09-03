
"""Launch Conduit through the environment created by setup.py."""
from __future__ import annotations
from pathlib import Path
import os, subprocess, sys

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")


def main() -> int:
    if not VENV_PYTHON.exists():
        print("Conduit has not been set up yet.")
        print("Run: py setup.py")
        return 1

    try:
        in_venv = Path(sys.executable).resolve() == VENV_PYTHON.resolve()
    except Exception:
        in_venv = False

    if not in_venv:
        result = subprocess.run(
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=ROOT,
            shell=False,
        )
        return int(result.returncode)

    from conduit.gui.bootstrap import launch_conduit
    return launch_conduit(project_root=ROOT, version="3.1.8")


if __name__ == "__main__":
    raise SystemExit(main())
