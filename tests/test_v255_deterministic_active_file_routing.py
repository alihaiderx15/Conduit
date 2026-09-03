
from pathlib import Path
from types import SimpleNamespace
import pytest
from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService
from conduit.file_processing.models import ProcessingResult

def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")

def test_image_dimensions_route_with_turn_word(tmp_path, monkeypatch):
    from PIL import Image
    from conduit.conversation import session as session_mod
    p=tmp_path/"1.jpeg"
    Image.new("RGB",(640,480)).save(p)
    service=make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod,"file_service",service)
    assert ConversationSession._could_be_file_processing_request("turn this pic to 1920x1080")

@pytest.mark.asyncio
async def test_image_dimensions_fast_resize(tmp_path, monkeypatch):
    from PIL import Image
    from conduit.conversation import session as session_mod
    p=tmp_path/"1.jpeg"
    Image.new("RGB",(640,480)).save(p)
    service=make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod,"file_service",service)
    session=object.__new__(ConversationSession)
    session.agent=SimpleNamespace(loop=SimpleNamespace(provider=None,model="none"))
    answer,report=await session._execute_file_processing_request("turn this pic to 1920x1080")
    assert report.success is True
    out=next(tmp_path.glob("1_resized_1920x1080*.jpeg"))
    with Image.open(out) as img:
        assert img.size==(1920,1080)

def test_typo_mp3_prompt_routes(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    p=tmp_path/"1.mp4"
    p.write_bytes(b"fake")
    service=make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod,"file_service",service)
    assert ConversationSession._could_be_file_processing_request("extrach the mp3 from 1.mp4")

@pytest.mark.asyncio
async def test_typo_mp3_prompt_fast_extract(tmp_path, monkeypatch):
    from conduit.conversation import session as session_mod
    from conduit.file_processing import service as service_mod
    p=tmp_path/"1.mp4"
    p.write_bytes(b"fake")
    service=make_service(tmp_path)
    service.register_dropped_file(p)
    monkeypatch.setattr(session_mod,"file_service",service)
    captured={}
    def fake_media(item, action, params):
        captured.update(item=item, action=action, params=dict(params))
        return ProcessingResult(True, action, "Extracted video audio as MP3.", item)
    monkeypatch.setattr(service_mod.media_adapter,"process",fake_media)
    session=object.__new__(ConversationSession)
    session.agent=SimpleNamespace(loop=SimpleNamespace(provider=None,model="none"))
    answer,report=await session._execute_file_processing_request("extrach the mp3 from 1.mp4")
    assert report.success is True
    assert captured["item"].path==p.resolve()
    assert captured["action"]=="extract_audio"
    assert captured["params"]["format"]=="mp3"

def test_sentence_ending_filename_uses_active_file(tmp_path):
    p=tmp_path/"1.mp4"
    p.write_bytes(b"fake")
    service=make_service(tmp_path)
    service.register_dropped_file(p)
    assert service._resolve("extrach the mp3 from 1.mp4").path==p.resolve()

def test_version_255():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
