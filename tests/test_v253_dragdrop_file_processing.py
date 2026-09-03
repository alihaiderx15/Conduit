
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.file_processing import FileProcessingService
from conduit.file_processing.models import ProcessingResult


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


def test_active_image_request_with_pic_and_dimensions_routes_to_file_processing(tmp_path, monkeypatch):
    from PIL import Image
    from conduit.conversation import session as session_mod

    image = tmp_path/"1.jpeg"
    Image.new("RGB", (640, 480)).save(image)

    service = make_service(tmp_path)
    service.register_dropped_file(image)

    monkeypatch.setattr(session_mod, "file_service", service)

    assert ConversationSession._could_be_file_processing_request(
        "convert the pic into 1920x1080"
    )


@pytest.mark.asyncio
async def test_active_image_resize_uses_dropped_file_and_exact_dimensions(tmp_path, monkeypatch):
    from PIL import Image
    from conduit.conversation import session as session_mod

    image = tmp_path/"1.jpeg"
    Image.new("RGB", (640, 480)).save(image)

    service = make_service(tmp_path)
    service.register_dropped_file(image)
    monkeypatch.setattr(session_mod, "file_service", service)

    session = object.__new__(ConversationSession)
    session.agent = SimpleNamespace(loop=SimpleNamespace(provider=None, model="none"))

    answer, report = await session._execute_file_processing_request(
        "convert the pic into 1920x1080"
    )

    assert report.success is True
    assert "1920x1080" in answer
    output = next(tmp_path.glob("1_resized_1920x1080*.jpeg"))
    with Image.open(output) as img:
        assert img.size == (1920, 1080)


def test_service_ignores_natural_language_in_path_when_gui_file_is_active(tmp_path):
    from PIL import Image

    image = tmp_path/"1.jpeg"
    Image.new("RGB", (20, 20)).save(image)

    service = make_service(tmp_path)
    service.register_dropped_file(image)

    result = service.process(
        action="resize",
        path="convert the pic into 30x40",
        parameters={"width": 30, "height": 40, "keep_aspect": False},
    )

    assert result.success
    assert result.input_file.path == image.resolve()


def test_service_normalizes_convert_to_mp3_for_active_video(tmp_path, monkeypatch):
    from conduit.file_processing import service as service_mod

    video = tmp_path/"1.mp4"
    video.write_bytes(b"fake video")
    service = make_service(tmp_path)
    service.register_dropped_file(video)

    captured = {}

    def fake_process(item, action, params):
        captured["item"] = item
        captured["action"] = action
        captured["params"] = dict(params)
        return ProcessingResult(True, action, "ok", item)

    monkeypatch.setattr(service_mod.media_adapter, "process", fake_process)

    result = service.process(
        action="convert_to_mp3",
        parameters={},
    )

    assert result.success
    assert captured["action"] == "extract_audio"
    assert captured["params"]["format"] == "mp3"
    assert captured["item"].path == video.resolve()


def test_user_prompt_is_present_in_debug_console_again():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert 'self.signals.console.emit("USER", command)' in source


def test_right_chat_behavior_is_preserved():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert "self.chat.add_user(text)" in source
    assert "self.chat.add_conduit(answer, success)" in source


def test_version_253():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
