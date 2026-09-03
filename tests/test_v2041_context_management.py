
from pathlib import Path
from types import SimpleNamespace

import pytest

from conduit.core.models import ChatMessage, Role
from conduit.providers.ollama import OllamaProvider


class CaptureOllama(OllamaProvider):
    def __init__(self, *, num_ctx=8192):
        super().__init__(base_url="http://localhost:1", num_ctx=num_ctx)
        self.payloads = []

    async def _post_chat(self, payload):
        self.payloads.append(payload)
        return {"model": payload["model"], "message": {"content": "OK"}}


@pytest.mark.asyncio
async def test_ollama_normal_chat_keeps_core_prompt_and_8k_context():
    provider = CaptureOllama(num_ctx=8192)
    await provider.chat(
        [ChatMessage(Role.USER, "hello")],
        model="qwen2.5vl:7b",
    )
    payload = provider.payloads[-1]
    assert payload["options"]["num_ctx"] == 8192
    assert payload["messages"][0]["role"] == "system"
    assert "CONDUIT CORE PROTOCOL" in payload["messages"][0]["content"]


@pytest.mark.asyncio
async def test_ollama_specialist_chat_omits_large_core_prompt():
    provider = CaptureOllama(num_ctx=8192)
    await provider.specialist_chat(
        [ChatMessage(Role.USER, "Rewrite this professionally.")],
        model="qwen2.5vl:7b",
    )
    payload = provider.payloads[-1]
    assert payload["options"]["num_ctx"] == 8192
    assert len(payload["messages"]) == 1
    assert payload["messages"][0]["role"] == "user"
    assert "CONDUIT CORE PROTOCOL" not in payload["messages"][0]["content"]


def test_ollama_default_context_is_8192(monkeypatch):
    monkeypatch.delenv("CONDUIT_OLLAMA_NUM_CTX", raising=False)
    provider = OllamaProvider(base_url="http://localhost:1")
    assert provider._num_ctx == 8192


def test_ollama_context_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CONDUIT_OLLAMA_NUM_CTX", "12288")
    provider = OllamaProvider(base_url="http://localhost:1")
    assert provider._num_ctx == 12288


def test_message_writer_and_auditor_use_specialist_channel():
    from conduit.conversation import session
    source = Path(session.__file__).read_text(encoding="utf-8")
    block = source[
        source.index("async def _compose_messaging_text"):
        source.index("async def _prepare_messaging_client")
    ]
    assert '"specialist_chat"' in block
    assert "drafted = await specialist" in block
    assert "audited = await specialist" in block


def test_messaging_intent_router_uses_specialist_channel():
    root = Path(__file__).resolve().parents[1]
    source = (root / "conduit" / "messaging" / "planner.py").read_text(encoding="utf-8")
    assert '"specialist_chat"' in source
