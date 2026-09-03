
from conduit.tools import builtin as b


def test_single_missing_app_is_clean_result_not_exception(monkeypatch):
    def missing(app):
        raise b._system_windows.SystemControlError(
            f"I couldn't find an installed app matching {app!r}."
        )

    monkeypatch.setattr(b._system_windows, "open_app", missing)

    result = b.system_open_app("calender")

    assert result.success is False
    assert result.message == "calender is not installed."
    assert result.error_type == "AppNotInstalled"
    assert result.data["installed"] is False


def test_multiple_apps_report_missing_app_by_name(monkeypatch):
    monkeypatch.setattr(
        b._system_windows,
        "open_apps",
        lambda apps: {
            "opened": [{"name": "Discord", "requested": "discord"}],
            "errors": [{
                "app": "calender",
                "error": "I couldn't find an installed app matching 'calender'.",
            }],
        },
    )

    result = b.system_open_apps(["discord", "calender"])

    assert result.success is True
    assert result.message == "Opened Discord. calender is not installed."
    assert result.error_type == "PartialAppOpen"


def test_non_missing_open_error_still_raises(monkeypatch):
    def failure(app):
        raise b._system_windows.SystemControlError("Windows denied launch.")

    monkeypatch.setattr(b._system_windows, "open_app", failure)

    try:
        b.system_open_app("discord")
    except b._system_windows.SystemControlError as exc:
        assert "denied" in str(exc).casefold()
    else:
        raise AssertionError("Unexpected non-missing launch errors must still raise.")


def test_version_233():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
