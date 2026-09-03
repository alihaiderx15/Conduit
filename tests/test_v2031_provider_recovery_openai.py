
from pathlib import Path

from conduit.providers.console_recovery import _choose_openai_model


def test_openai_model_auto_selection_prefers_general_gpt_model():
    models = [
        "gpt-realtime",
        "gpt-4o",
        "gpt-5-mini",
        "text-embedding-3-small",
    ]
    assert _choose_openai_model(models) == "gpt-5-mini"


def test_openai_provider_exists_and_supports_vision_transport():
    from conduit.providers.openai import OpenAIProvider
    provider = OpenAIProvider("test-key", base_url="http://localhost:1")
    assert provider.provider_id == "openai"
    assert provider.capabilities.vision
    assert provider.capabilities.tools


def test_gemini_vision_maps_quota_for_recovery():
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit" / "providers" / "gemini.py").read_text(encoding="utf-8")
    block = source[source.index("async def describe_image"):]
    assert "ProviderQuotaError" in block
    assert '"429"' in block
    assert "ProviderAuthenticationError" in block


def test_messaging_vision_retries_through_provider_recovery():
    from conduit.messaging import service
    source = Path(service.__file__).read_text(encoding="utf-8")
    assert "recover_provider_error" in source
    assert "observe_messaging_description" in source
    assert "for attempt in range(2)" in source


def test_shell_supports_openai_and_ollama_model_selection():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert 'choices=("gemini", "ollama", "openai")' in source
    assert "switch_to_openai" in source
    assert "_select_ollama_model(candidate)" in source
    assert "/switch openai" in source


def test_masked_key_input_is_used_in_shell_and_recovery():
    root = Path(__file__).resolve().parents[1]
    shell = (root / "scripts" / "conduit_chat.py").read_text(encoding="utf-8")
    recovery = (root / "conduit" / "providers" / "console_recovery.py").read_text(encoding="utf-8")
    assert "masked_input" in shell
    assert "masked_input" in recovery
    assert "getpass.getpass" not in shell
