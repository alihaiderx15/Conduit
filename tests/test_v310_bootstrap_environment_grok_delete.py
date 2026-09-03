
from pathlib import Path
from types import SimpleNamespace

from conduit.environment import EnvironmentService
from conduit.model_advisor import ollama_catalog
from conduit.providers.grok import GrokProvider
from conduit.providers.console_recovery import _choose_grok_model
from conduit.conversation.session import ConversationSession


def test_ollama_catalog_always_offers_two_beginner_models_when_missing():
    rows = ollama_catalog([])
    names = {row["name"]: row for row in rows}
    assert "qwen2.5vl:7b" in names
    assert "qwen2.5-coder:7b" in names
    assert names["qwen2.5vl:7b"]["installed"] is False
    assert names["qwen2.5-coder:7b"]["installed"] is False
    # The backend catalog may contain additional specialists; the GUI filters
    # missing recommendations to the two beginner models.
    assert "devstral-small-2" in names


def test_installed_recommended_model_is_not_duplicated():
    rows = ollama_catalog(["qwen2.5vl:7b"])
    assert [row["name"] for row in rows].count("qwen2.5vl:7b") == 1
    installed = next(row for row in rows if row["name"] == "qwen2.5vl:7b")
    assert installed["installed"] is True


def test_grok_provider_uses_xai_endpoint():
    provider = GrokProvider("test-key")
    assert provider.provider_id == "grok"
    assert str(provider._client.base_url).startswith("https://api.x.ai/v1")
    import asyncio
    asyncio.run(provider.close())


def test_grok_model_selector_prefers_current_primary_model():
    models = ["grok-imagine-image", "grok-3", "grok-4.6"]
    assert _choose_grok_model(models) == "grok-4.6"


def test_environment_required_actions_registered():
    from conduit.tools.builtin import registry
    names = {item.name for item in registry.all()}
    assert {
        "environment.check",
        "environment.install_optional_feature",
        "environment.verify_browser",
        "environment.verify_ollama",
        "environment.verify_model",
    } <= names


def test_environment_has_two_recommended_models():
    names = [name for name, _ in EnvironmentService.RECOMMENDED_OLLAMA_MODELS]
    assert names == ["qwen2.5vl:7b", "qwen2.5-coder:7b"]


def test_setup_and_main_entrypoints_exist():
    root = Path(__file__).resolve().parents[1]
    setup = (root/"setup.py").read_text(encoding="utf-8")
    main = (root/"main.py").read_text(encoding="utf-8")
    assert 'pip", "install", "-e", ".[file_processing_extra]"' in setup
    assert '"playwright", "install", "chromium"' in setup
    assert "launch_conduit" in main


def test_bootstrap_contains_all_provider_choices_and_ollama_installer():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/bootstrap.py").read_text(encoding="utf-8")
    for label in ("OLLAMA", "GEMINI", "OPENAI", "GROK AI"):
        assert label in source
    assert "start_ollama_installer" in source
    assert "qwen2.5vl:7b" in source
    assert "qwen2.5-coder:7b" in source


def test_ollama_installer_uses_requested_powershell_command():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/environment/service.py").read_text(encoding="utf-8")
    assert 'irm https://ollama.com/install.ps1 | iex' in source
    assert '"powershell.exe"' in source


def test_delete_recent_file_helper(tmp_path, monkeypatch):
    target = tmp_path/"generated.py"
    target.write_text("print('x')", encoding="utf-8")
    session = object.__new__(ConversationSession)
    session._file_context = {"last_artifact_path": str(target)}
    monkeypatch.setattr(session, "_latest_artifact_path", lambda: target)
    answer, report = session._delete_recent_artifact()
    assert report.success is True
    assert answer == "Deleted generated.py."
    assert not target.exists()


def test_delete_recent_file_intent():
    assert ConversationSession._is_delete_recent_artifact("delete that file")
    assert ConversationSession._is_delete_recent_artifact("remove the latest file")
    assert not ConversationSession._is_delete_recent_artifact("delete that folder")


def test_version_310():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
