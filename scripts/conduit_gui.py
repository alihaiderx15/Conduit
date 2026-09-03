
r"""Launch the Conduit cyberpunk desktop GUI.

Examples:
    py scripts\conduit_gui.py ollama --model qwen2.5vl:7b
    py scripts\conduit_gui.py gemini --model gemini-flash-latest
"""
from __future__ import annotations

import argparse
from pathlib import Path

from conduit.gui import run_gui


def main() -> int:
    parser = argparse.ArgumentParser(description="Conduit desktop GUI")
    parser.add_argument("provider", choices=("gemini", "ollama", "openai", "grok"))
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Disable Conduit's persistent conversation memory.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    return run_gui(
        provider=args.provider,
        model=args.model,
        project_root=project_root,
        no_memory=args.no_memory,
        version="3.1.8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
