
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


def test_convert_this_to_pdf_routes_as_file_processing(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    p = tmp_path/"1.txt"
    p.write_text("hello world", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)

    assert ConversationSession._could_be_file_processing_request("convert this to pdf")


@pytest.mark.asyncio
async def test_convert_active_txt_to_pdf_uses_fast_plan(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod

    p = tmp_path/"1.txt"
    p.write_text("hello world from conduit", encoding="utf-8")
    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))

    answer, report = await session._execute_file_processing_request("convert this to pdf")

    assert report.success is True
    outputs = list(tmp_path.glob("1_converted*.pdf"))
    assert len(outputs) == 1
    assert outputs[0].stat().st_size > 0
    assert "Saved output to" in answer


@pytest.mark.asyncio
async def test_convert_active_docx_to_pdf_uses_fast_plan(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    from docx import Document

    p = tmp_path/"1.docx"
    d = Document()
    d.add_paragraph("hello from docx")
    d.save(p)

    service = make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))

    answer, report = await session._execute_file_processing_request("turn this into pdf")

    assert report.success is True
    assert list(tmp_path.glob("1_converted*.pdf"))


def test_version_259():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
