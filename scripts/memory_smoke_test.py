"""Manual persistence smoke test for Module 9 local memory."""

from __future__ import annotations

import argparse
from pathlib import Path

from conduit.memory import MemoryCategory, MemoryManager, MemoryRetriever, SensitiveMemoryError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/conduit-smoke.db")
    args = parser.parse_args()
    path = Path(args.database)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    print(f"Database: {path.resolve()}")
    print("\nOpening memory system and writing records...")
    with MemoryManager(path) as memory:
        provider = memory.remember(
            "preferred_provider",
            "Ollama",
            category=MemoryCategory.PREFERENCE,
            importance=0.9,
        )
        memory.remember(
            "browser_automation",
            "Conduit uses Playwright for browser automation.",
            importance=0.9,
        )
        project = memory.create_project("Conduit", description="Desktop AI agent")
        memory.remember_project_fact(project.id, "current_phase", "Module 9 local memory")
        conversation = memory.repository.create_conversation("Memory smoke test")
        memory.repository.add_message(conversation.id, "user", "Remember my preferred provider.")
        memory.repository.add_message(conversation.id, "assistant", "Your preferred provider is Ollama.")
        print(f"Saved preference id={provider.id}")

        try:
            memory.remember("api_key", "api_key=do-not-store-this-secret")
        except SensitiveMemoryError as exc:
            print(f"Sensitive-memory protection: PASS ({exc})")
        else:
            raise RuntimeError("Sensitive-memory protection failed.")

    print("\nMemory system closed. Reopening the same SQLite file...")
    with MemoryManager(path) as memory:
        preference = memory.repository.get_memory(MemoryCategory.PREFERENCE, "preferred_provider")
        assert preference and preference.value == "Ollama"
        print(f"Persisted preference: {preference.key} = {preference.value}")

        results = memory.recall("browser automation")
        assert results
        print("Search result:")
        for result in results:
            print(f"  {result.record.key}: {result.record.value}")

        context = MemoryRetriever(memory).context_for("Playwright")
        print("\nPrompt context:")
        print(context)

        updated = memory.remember(
            "preferred_provider",
            "Gemini for cloud, Ollama for private local use",
            category=MemoryCategory.PREFERENCE,
            importance=1.0,
        )
        assert updated.id == preference.id
        print(f"\nUpdated preference: {updated.value}")

        assert memory.forget(updated.id)
        assert memory.repository.get_memory(MemoryCategory.PREFERENCE, "preferred_provider") is None
        print("Delete test: PASS")

    print("\nMODULE 9 MEMORY SMOKE TEST: PASS")


if __name__ == "__main__":
    main()
