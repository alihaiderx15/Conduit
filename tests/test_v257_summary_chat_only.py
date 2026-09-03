
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


def test_short_summary_normalizer_caps_at_30_words():
    text = " ".join(f"word{i}" for i in range(1, 41))
    result = ConversationSession._normalize_short_summary(text)
    assert len(result.rstrip(".").split()) == 30
    assert result.endswith(".")


@pytest.mark.asyncio
async def test_normal_summary_returns_chat_only_and_does_not_create_summary_file(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod

    doc = tmp_path/"1.txt"
    doc.write_text(
        "This is a test document with enough information to summarize meaningfully.",
        encoding="utf-8",
    )
    service = make_service(tmp_path)
    service.register_dropped_file(doc)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))

    async def fake_complete(result):
        return (
            "This document explains its main topic, highlights the most important "
            "details, and gives the essential information required to understand "
            "its overall purpose clearly."
        )
    monkeypatch.setattr(session, "_complete_file_semantic_result", fake_complete)

    before = set(tmp_path.iterdir())
    answer, report = await session._execute_file_processing_request("summarize this file")
    after = set(tmp_path.iterdir())

    assert report.success is True
    assert 20 <= len(answer.rstrip(".").split()) <= 30
    assert before == after
    assert not list(tmp_path.glob("*_summary*.txt"))
    assert "Saved output to" not in answer


@pytest.mark.asyncio
async def test_explicit_summary_file_request_creates_summary_file(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod

    doc = tmp_path/"1.txt"
    doc.write_text("This is a test document with important information.", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(doc)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))

    async def fake_complete(result):
        return (
            "This document presents its essential information in a concise form, "
            "covering the central topic and most important details for quick reference."
        )
    monkeypatch.setattr(session, "_complete_file_semantic_result", fake_complete)

    answer, report = await session._execute_file_processing_request(
        "generate a summary file for this document"
    )

    assert report.success is True
    files = list(tmp_path.glob("*_summary*.txt"))
    assert len(files) == 1
    assert "Saved output to" in answer


def test_version_257():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
