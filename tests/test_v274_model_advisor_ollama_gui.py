
from pathlib import Path

from conduit.model_advisor import (
    classify_task,
    current_model_is_suitable,
    describe_ollama_model,
    ollama_catalog,
    recommended_model,
    valid_ollama_model_name,
)


def test_code_task_recommends_devstral():
    assert classify_task("generate a python snake game") == "coding"
    profile = recommended_model("coding")
    assert profile is not None
    assert profile.name == "devstral-small-2"


def test_vision_task_recommends_qwen_vl():
    assert classify_task("describe this image", active_file_kind="image") == "vision"
    profile = recommended_model("vision")
    assert profile is not None
    assert profile.name == "qwen2.5vl:7b"


def test_model_suitability():
    assert current_model_is_suitable("devstral-small-2", "coding")
    assert current_model_is_suitable("qwen3-coder:30b", "coding")
    assert not current_model_is_suitable("qwen2.5vl:7b", "coding")
    assert current_model_is_suitable("qwen2.5vl:7b", "vision")
    assert not current_model_is_suitable("devstral-small-2", "vision")


def test_catalog_contains_installed_and_curated_downloads():
    rows = ollama_catalog(["qwen2.5vl:7b", "my-local-model:latest"])
    names = {row["name"]: row for row in rows}
    assert names["qwen2.5vl:7b"]["installed"] is True
    assert names["my-local-model:latest"]["installed"] is True
    assert names["devstral-small-2"]["installed"] is False
    assert names["devstral-small-2"]["description"] == "Coding • Agentic"


def test_short_model_descriptions():
    assert "Coding" in describe_ollama_model("qwen2.5-coder:7b")
    assert "Vision" in describe_ollama_model("qwen2.5vl:7b")


def test_ollama_model_name_validation_blocks_command_injection():
    assert valid_ollama_model_name("devstral-small-2")
    assert valid_ollama_model_name("qwen3-coder:30b")
    assert not valid_ollama_model_name("devstral-small-2 && whoami")
    assert not valid_ollama_model_name("model; rm -rf /")


def test_runtime_uses_visible_cmd_without_shell_true():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert '["cmd.exe", "/c", "ollama", "pull", model]' in source
    assert "CREATE_NEW_CONSOLE" in source
    assert "shell=False" in source
    assert '"ollama_ensure"' in source
    assert '"ollama_switch"' in source


def test_gui_has_three_provider_buttons_and_model_advisor():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert 'QPushButton("OLLAMA")' in source
    assert 'QPushButton("GEMINI")' in source
    assert 'QPushButton("OPENAI")' in source
    assert "OLLAMA MODEL SELECTOR" in source
    assert "Better AI Model Available" in source
    assert "DOWNLOAD & USE" in source
    assert "_resume_pending_model_task" in source


def test_version_274():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
