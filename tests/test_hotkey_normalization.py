
from conduit.actions.router import _normalize_hotkey_keys
from conduit.approvals.models import _normalize_constraint_value


def test_hotkey_router_accepts_common_model_encodings():
    assert _normalize_hotkey_keys(["ctrl", "a"]) == ["ctrl", "a"]
    assert _normalize_hotkey_keys("ctrl+a") == ["ctrl", "a"]
    assert _normalize_hotkey_keys("CTRL, C") == ["ctrl", "c"]


def test_approval_normalizes_hotkey_encodings():
    assert _normalize_constraint_value("keys", "ctrl+a") == ("ctrl", "a")
    assert _normalize_constraint_value("keys", ["CTRL", "A"]) == ("ctrl", "a")
    assert _normalize_constraint_value("keys", ("ctrl", "a")) == ("ctrl", "a")
