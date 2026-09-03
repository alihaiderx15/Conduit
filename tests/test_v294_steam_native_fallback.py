
from pathlib import Path

def test_native_steam_uia_fallback_exists():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/games/service.py").read_text(encoding="utf-8")
    assert "def activate_steam_update_uia" in source
    assert 'Desktop(backend="uia")' in source
    assert "target.invoke()" in source
    assert "target.click_input()" in source

def test_update_flow_uses_uri_then_uia_then_visual():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/conversation/session.py").read_text(encoding="utf-8")
    uri = source.index("confirmed, verified = await verify_steam_state(8)")
    uia = source.index("activate_steam_update_uia", uri)
    visual = source.index("_activate_steam_scheduled_update(game)", uia)
    assert uri < uia < visual

def test_version_294():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
