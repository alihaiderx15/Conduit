
from conduit.providers.fault_injection import FailAfterNProvider
from conduit.providers.recovery import ProviderReplacement
from conduit.core.models import ProviderCapabilities
from conduit.providers.base import AIProvider

class Dummy(AIProvider):
    provider_id="dummy"
    @property
    def capabilities(self): return ProviderCapabilities(chat=True, tools=False, vision=False, streaming=False)
    async def list_models(self): return ["dummy"]
    async def chat(self, messages, *, model, tools=()): raise AssertionError("not used")

def test_fault_injector_preserves_capabilities():
    wrapped=FailAfterNProvider(Dummy(), fail_after_calls=1)
    assert wrapped.provider_id=="dummy"
    assert wrapped.capabilities.chat

def test_replacement_records_reason():
    r=ProviderReplacement(Dummy(),"dummy","resume")
    assert r.reason=="resume"
