
from conduit.providers.console_recovery import _retry_after_seconds


def test_retry_hint_parsing():
    assert _retry_after_seconds("Please retry in 45.320325676s.") == 45.320325676
    assert _retry_after_seconds("retry in 30 seconds") == 30.0
    assert _retry_after_seconds("no hint") is None
