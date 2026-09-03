"""Unseen natural-language benchmark for General PC Agent v1.2.

The benchmark seeds two text files with different modification times. The agent
must discover the newest one, read it, move its exact contents through the
clipboard into Notepad, resize the window, and verify the final state.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path

from conduit.events import EventBus
from conduit.general_pc import GeneralPCAgent, GeneralPCAgentConfig
from conduit.providers.console_recovery import ConsoleProviderRecovery
from conduit.providers.gemini import GeminiProvider
from conduit.providers.ollama import OllamaProvider


EXPECTED = "Conduit v1.2 discovered the newest file and completed the task."
TARGET_BOUNDS = {"x": 120, "y": 100, "width": 900, "height": 600}


def seed_files(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    older = root / "older-note.txt"
    newest = root / "newest-note.txt"
    older.write_text("This is the older file and must not be selected.", encoding="utf-8")
    newest.write_text(EXPECTED, encoding="utf-8")
    now = time.time()
    os.utime(older, (now - 120, now - 120))
    os.utime(newest, (now, now))
    return older, newest


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("gemini", "ollama"))
    parser.add_argument("--model", required=True)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    source_dir = (project_root / "data" / "v12-unseen-source").resolve()
    _, newest = seed_files(source_dir)

    if args.provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise SystemExit("Set GEMINI_API_KEY before running the Gemini test.")
        provider = GeminiProvider(api_key=key)
    else:
        provider = OllamaProvider()

    goal = (
        f"In the folder {source_dir}, identify the most recent text file using file metadata. "
        "Read that file and place its exact contents on the Windows clipboard. Open Notepad, "
        "activate its window, and paste the clipboard text using Ctrl+V. Move and resize the "
        f"Notepad window to x={TARGET_BOUNDS['x']}, y={TARGET_BOUNDS['y']}, "
        f"width={TARGET_BOUNDS['width']}, height={TARGET_BOUNDS['height']}. "
        "Read the clipboard again, inspect the final Notepad window bounds, and verify that "
        "notepad.exe is running. Do not modify, rename, move, or delete either source file. "
        "Finish only after structured evidence proves every requirement."
    )

    print("\nGENERAL PC AGENT V1.2 — UNSEEN TASK\n")
    print(goal)
    print("\nTask-intent consent is active:")
    print("- ordinary task actions run without repeated prompts")
    print("- destructive actions such as file deletion still require confirmation")

    events = EventBus()

    async def show(event):
        if event.name.startswith((
            "general_pc.",
            "agent.decision",
            "agent.observation",
            "agent.finish",
            "agent.goal",
            "agent.provider",
            "execution.confirmation",
        )):
            print(f"EVENT {event.name}: {dict(event.payload)}")

    events.subscribe("*", show)

    agent = await GeneralPCAgent.create(
        provider=provider,
        model=args.model,
        config=GeneralPCAgentConfig(max_iterations=24),
        event_bus=events,
        provider_recovery_handler=ConsoleProviderRecovery(
            ollama_model="qwen3:8b",
            gemini_model=args.model if args.provider == "gemini" else "gemini-flash-latest",
        ),
    )

    try:
        report = await agent.run(
            goal,
            initial_variables={
                "source_dir": str(source_dir),
                "expected_source_path": str(newest),
                "expected_text": EXPECTED,
                "target_window_bounds": dict(TARGET_BOUNDS),
            },
        )
    finally:
        await agent.close()

    actions = [item.action for item in report.observations if item.success]
    required = {
        "files.list_recent",
        "files.read_text",
        "clipboard.write",
        "clipboard.read",
        "system.open_app",
        "system.activate_window",
        "desktop.hotkey",
        "system.move_resize_window",
        "system.window_bounds",
        "system.process_info",
    }
    missing = sorted(required - set(actions))

    print("\nUNSEEN TASK REPORT")
    for observation in report.observations:
        state = "OK" if observation.success else "FAILED"
        print(f"  [{state}] {observation.action}: {observation.message}")
    print("STATUS:", report.status.value)
    print("SUCCESS:", report.success)
    print("MISSING REQUIRED ACTION EVIDENCE:", missing or "none")

    if not report.success or missing:
        raise SystemExit("GENERAL PC AGENT V1.2 UNSEEN TEST: FAILED")
    print("GENERAL PC AGENT V1.2 UNSEEN TEST: PASS")


if __name__ == "__main__":
    asyncio.run(main())
