
from pathlib import Path
import inspect
import pytest
from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserSession

def test_scanner_uses_ctrl1_and_pagedown():
    src=inspect.getsource(BrowserEngine._native_collect_tabs_for_window)
    assert '_native_hotkey("ctrl", "1")' in src
    assert '_native_hotkey("ctrl", "pagedown")' in src
    assert '_native_hotkey("ctrl", "tab")' not in src

def test_gmail_alias_matches_mail_google():
    item={"title":"Inbox (3,990) - alihaider","url":"https://mail.google.com/mail/u/0/#inbox"}
    assert BrowserEngine._native_tab_matches(item,"Gmail")

def test_youtube_alias_matches_url():
    item={"title":"(144) Video","url":"https://www.youtube.com/watch?v=abc"}
    assert BrowserEngine._native_tab_matches(item,"youtube")

@pytest.mark.asyncio
async def test_named_gmail_switch_uses_url_alias(monkeypatch):
    engine=BrowserEngine()
    session=engine._register_session(BrowserSession(
        "opera-gx-1","opera gx","chromium","real_profile","native",pid=1
    ))
    engine._select_session(session)
    tabs=[{"index":5,"title":"Inbox (3,990) - alihaider",
           "url":"https://mail.google.com/mail/u/0/#inbox",
           "window_hwnd":100,"window_pid":1,"window_tab_order":5}]
    hit=[]
    async def collect(_): return tabs
    async def activate(_,item): hit.append(item["index"])
    async def state(**kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("Inbox","","",0,0)
    monkeypatch.setattr(engine,"_native_collect_all_tabs",collect)
    monkeypatch.setattr(engine,"_native_activate_inventory_tab",activate)
    monkeypatch.setattr(engine,"state",state)
    await engine.switch_tab("Gmail")
    assert hit == [5]

def test_version():
    assert 'version = "3.1.8"' in (Path(__file__).resolve().parents[1]/"pyproject.toml").read_text()
