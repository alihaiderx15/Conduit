
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService
from conduit.file_processing.models import ProcessingResult


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


def test_word_count_routes_with_active_doc(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    p = tmp_path/"1.txt"
    p.write_text("one two three", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)
    assert ConversationSession._could_be_file_processing_request("count words")


@pytest.mark.asyncio
async def test_word_count_active_doc_fast_plan(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    p = tmp_path/"1.txt"
    p.write_text("one two three", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)
    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))
    answer, report = await session._execute_file_processing_request("count words")
    assert report.success is True
    assert "3 words" in answer


@pytest.mark.asyncio
async def test_bullet_points_active_doc_fast_plan(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    p = tmp_path/"1.txt"
    p.write_text("First sentence. Second sentence.", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)
    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))
    answer, report = await session._execute_file_processing_request("Convert to bullet points")
    assert report.success is True
    assert "bullet" in answer.casefold()
    assert list(tmp_path.glob("1_bullets*.txt"))


@pytest.mark.asyncio
async def test_trim_active_video_fast_plan(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    from conduit.file_processing import service as service_mod
    p = tmp_path/"1.mp4"
    p.write_bytes(b"fake")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)

    captured = {}
    def fake_media(item, action, params):
        captured.update(item=item, action=action, params=dict(params))
        return ProcessingResult(True, action, "Trimmed media file.", item)

    monkeypatch.setattr(service_mod.media_adapter, "process", fake_media)
    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))
    answer, report = await session._execute_file_processing_request("trim this from 00:07 to 00:08")
    assert report.success is True
    assert captured["action"] == "trim"
    assert captured["params"]["start"] == "00:07"
    assert captured["params"]["end"] == "00:08"


def test_version_260():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
