import pytest

from conduit.browser import BrowserTarget, TargetKind


def test_target_requires_value():
    with pytest.raises(ValueError):
        BrowserTarget(TargetKind.TEXT, "  ")


def test_target_keeps_semantic_fields():
    target = BrowserTarget(TargetKind.ROLE, "button", name="Submit", exact=True)
    assert target.kind is TargetKind.ROLE
    assert target.name == "Submit"
    assert target.exact is True
