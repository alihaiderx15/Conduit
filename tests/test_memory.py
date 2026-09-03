from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from conduit.memory import (
    MemoryCategory,
    MemoryManager,
    MemoryRetriever,
    SensitiveMemoryError,
)


def test_memory_persists_across_restart(tmp_path):
    path = tmp_path / "conduit.db"
    with MemoryManager(path) as manager:
        saved = manager.remember(
            "preferred_provider",
            "Ollama",
            category=MemoryCategory.PREFERENCE,
            importance=0.9,
        )
        saved_id = saved.id

    with MemoryManager(path) as manager:
        record = manager.repository.get_memory(MemoryCategory.PREFERENCE, "preferred_provider")
        assert record is not None
        assert record.id == saved_id
        assert record.value == "Ollama"


def test_upsert_updates_existing_memory(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        first = manager.remember("theme", "dark", category=MemoryCategory.PREFERENCE)
        second = manager.remember("theme", "system", category=MemoryCategory.PREFERENCE)
        assert first.id == second.id
        assert second.value == "system"


def test_search_and_retrieval_context(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        manager.remember("browser_engine", "Conduit uses Playwright for browser automation")
        manager.remember("desktop_engine", "Conduit uses PyAutoGUI for desktop control")
        results = manager.recall("browser automation")
        assert results
        assert results[0].record.key == "browser_engine"
        context = MemoryRetriever(manager).context_for("Playwright")
        assert "browser_engine" in context
        assert "Playwright" in context


def test_sensitive_values_are_rejected(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        with pytest.raises(SensitiveMemoryError):
            manager.remember("gemini api key", "AIzaThisShouldNeverBeStored123456789")
        with pytest.raises(SensitiveMemoryError):
            manager.remember("login", "password=super-secret")


def test_expired_memories_are_hidden_and_purged(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        manager.remember(
            "temporary",
            "expires immediately",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert manager.repository.get_memory(MemoryCategory.FACT, "temporary") is None
        assert manager.repository.purge_expired() == 1


def test_conversation_messages_and_cascade(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        conversation = manager.repository.create_conversation("Test")
        manager.repository.add_message(conversation.id, "user", "Hello")
        manager.repository.add_message(conversation.id, "assistant", "Good afternoon.")
        messages = manager.repository.get_messages(conversation.id)
        assert [message.role for message in messages] == ["user", "assistant"]
        assert [message.content for message in messages] == ["Hello", "Good afternoon."]


def test_project_memory(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        project = manager.create_project("Conduit", description="Desktop AI agent", path="G:/CONDUIT")
        fact = manager.remember_project_fact(
            project.id,
            "browser_automation",
            "Uses Playwright",
            importance=0.9,
        )
        facts = manager.repository.get_project_facts(project.id)
        assert facts == (fact,)


def test_delete_and_clear(tmp_path):
    with MemoryManager(tmp_path / "conduit.db") as manager:
        one = manager.remember("one", "First")
        manager.remember("two", "Second")
        assert manager.forget(one.id)
        assert manager.repository.get_memory(MemoryCategory.FACT, "one") is None
        assert manager.repository.clear_memories() == 1
