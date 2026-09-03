
from pathlib import Path
import json
import zipfile

from conduit.file_processing import FileProcessingService, FileSource


def make_service(tmp_path):
    return FileProcessingService(state_path=tmp_path/"state.json")


def test_gui_drop_hook_sets_active_file(tmp_path):
    p=tmp_path/"note.txt"
    p.write_text("hello world",encoding="utf-8")
    service=make_service(tmp_path)

    item=service.register_dropped_file(p)

    assert item.source is FileSource.GUI_DROP
    assert service.get_active_file().path == p.resolve()


def test_text_word_count_uses_active_file(tmp_path):
    p=tmp_path/"note.txt"
    p.write_text("one two three four",encoding="utf-8")
    service=make_service(tmp_path)
    service.set_active_file(p)

    result=service.process(action="word_count")

    assert result.success
    assert result.data["words"] == 4


def test_json_validate_and_format(tmp_path):
    p=tmp_path/"data.json"
    p.write_text('{"a":1,"b":[2,3]}',encoding="utf-8")
    service=make_service(tmp_path)

    valid=service.process(action="validate",path=p)
    formatted=service.process(action="format",path=p)

    assert valid.success is True
    assert formatted.output_path.exists()
    assert json.loads(formatted.output_path.read_text(encoding="utf-8"))["a"] == 1


def test_zip_list_and_extract(tmp_path):
    p=tmp_path/"sample.zip"
    with zipfile.ZipFile(p,"w") as z:
        z.writestr("folder/a.txt","A")
        z.writestr("b.txt","B")
    service=make_service(tmp_path)

    listed=service.process(action="list",path=p)
    extracted=service.process(action="extract",path=p)

    assert listed.data["entry_count"] == 2
    assert (extracted.output_path/"folder/a.txt").read_text() == "A"


def test_capabilities_are_type_specific(tmp_path):
    p=tmp_path/"movie.mp4"
    p.write_bytes(b"fake")
    service=make_service(tmp_path)

    caps=service.capabilities(p)

    assert caps["file"]["kind"] == "video"
    assert "extract_audio" in caps["actions"]
    assert "extract_frame" in caps["actions"]


def test_processing_is_non_destructive(tmp_path):
    p=tmp_path/"note.txt"
    original="Sentence one. Sentence two."
    p.write_text(original,encoding="utf-8")
    service=make_service(tmp_path)

    result=service.process(action="bullet_points",path=p)

    assert p.read_text(encoding="utf-8") == original
    assert result.output_path != p
    assert result.output_path.exists()


def test_version_240():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
