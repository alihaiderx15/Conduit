
import pytest
from conduit.providers.recovery import ProviderReplacement
from conduit.core.errors import ProviderAuthenticationError, ProviderQuotaError

def test_recovery_types_are_provider_errors():
    assert issubclass(ProviderAuthenticationError, Exception)
    assert issubclass(ProviderQuotaError, Exception)

def test_provider_replacement_keeps_model():
    item = ProviderReplacement(provider=object(), model="qwen3:8b", reason="fallback")
    assert item.model == "qwen3:8b"
