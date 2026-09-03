"""Module 10 smoke test for Conduit's unified action layer."""
from __future__ import annotations
import asyncio
import tempfile
from pathlib import Path

from conduit.actions import UnifiedActionRegistry, register_default_actions
from conduit.core.models import ToolCall
from conduit.execution import ToolExecutor
from conduit.tools.builtin import registry


async def main() -> None:
    actions = register_default_actions(UnifiedActionRegistry(registry))
    print(f"Unified actions registered: {len(actions)}")
    for engine in ("tool", "browser", "desktop", "vision"):
        names = [item.name for item in actions.all() if item.engine.value == engine]
        print(f"{engine.upper()} ({len(names)}): {', '.join(names)}")

    executor = ToolExecutor(registry)
    with tempfile.TemporaryDirectory(prefix="conduit-actions-") as temp:
        root = Path(temp)
        note = root / "conduit-test.txt"
        print("\n1. Requesting a protected write without approval...")
        pending = await executor.execute(ToolCall("files.write_text", {"path": str(note), "text": "Conduit unified actions are working."}))
        print("PENDING:", pending)
        assert not note.exists()

        print("\n2. Approving the write...")
        written = await executor.execute(ToolCall("files.write_text", {"path": str(note), "text": "Conduit unified actions are working."}), confirmed=True)
        print("WRITE:", written)
        assert written.success and note.exists()

        print("\n3. Reading the created file...")
        read = await executor.execute(ToolCall("files.read_text", {"path": str(note)}))
        print("READ:", read)
        assert read.success and "unified actions" in read.data["text"]

        print("\n4. Searching for the file...")
        search = await executor.execute(ToolCall("files.search", {"root": str(root), "query": "conduit-test"}))
        print("SEARCH:", search)
        assert search.success and search.data["matches"]

        print("\n5. Verifying the path...")
        exists = await executor.execute(ToolCall("files.exists", {"path": str(note)}))
        print("EXISTS:", exists)
        assert exists.data["exists"] is True

    print("\nUNIFIED ACTION LAYER SMOKE TEST: PASS")


if __name__ == "__main__":
    asyncio.run(main())
