
from pathlib import Path
from types import SimpleNamespace
import pytest

from conduit.conversation.session import ConversationSession
from conduit.core.errors import ProviderQuotaError
from conduit.core.models import ProviderResponse


class QuotaProvider:
    provider_id = "gemini"
    async def specialist_chat(self, messages, *, model):
        raise ProviderQuotaError("Gemini quota unavailable. Please retry in 24.2s.")


class GoodProvider:
    provider_id = "openai"
    async def specialist_chat(self, messages, *, model):
        return ProviderResponse(text="corrected source", model=model)


class FakeAgent:
    def __init__(self):
        self.loop = SimpleNamespace(provider=QuotaProvider(), model="gemini-flash")
        self.recovery_calls = 0

    async def recover_provider_error(self, error):
        self.recovery_calls += 1
        assert isinstance(error, ProviderQuotaError)
        self.loop.provider = GoodProvider()
        self.loop.model = "gpt-test"
        return True


@pytest.mark.asyncio
async def test_code_helper_recovers_quota_and_retries_same_request():
    session = object.__new__(ConversationSession)
    session.agent = FakeAgent()
    text = await session._code_model_text("edit this code", timeout=5)
    assert text == "corrected source"
    assert session.agent.recovery_calls == 1
    assert session.agent.loop.model == "gpt-test"


def test_gui_runtime_registers_provider_recovery_handler():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "provider_recovery_handler=self._gui_provider_recovery" in source
    assert "provider_recovery_needed = Signal" in source
    assert "resolve_provider_recovery" in source
    assert '"alternate_model"' in source
    assert '"wait"' in source
    assert '"ollama"' in source


def test_gui_has_recovery_choices_and_masked_keys():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert "Use Another Gemini Key" in source
    assert "Use Another OpenAI Key" in source
    assert "Try Another Model" in source
    assert "Switch to Ollama" in source
    assert "Wait and Retry" in source
    assert "QLineEdit.Password" in source


def test_quota_raw_error_is_not_directly_added_to_chat_by_runtime_recovery():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert "Task paused for provider recovery" in source
    assert "provider_recovery_needed.emit" in source


def test_version_273():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
