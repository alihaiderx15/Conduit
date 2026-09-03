
from pathlib import Path
import pytest
from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserSession
from conduit.conversation import ConversationSession
class R:
    def __init__(self,message="ok",data=None): self.message=message; self.data=data or {}; self.success=True
@pytest.mark.asyncio
async def test_named_switch_finds_other_window(monkeypatch):
    engine=BrowserEngine(); session=engine._register_session(BrowserSession("opera-gx-1","opera gx","chromium","real_profile","native",pid=1)); engine._select_session(session)
    tabs=[{"index":1,"title":"Conduit","window_hwnd":100,"window_pid":1,"window_tab_order":1},{"index":2,"title":"YouTube","window_hwnd":200,"window_pid":2,"window_tab_order":1}]
    hit=[]
    async def collect(_): return tabs
    async def activate(_,item): hit.append(item["title"])
    async def state(**kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("YouTube","","",0,0)
    monkeypatch.setattr(engine,"_native_collect_all_tabs",collect); monkeypatch.setattr(engine,"_native_activate_inventory_tab",activate); monkeypatch.setattr(engine,"state",state)
    await engine.switch_tab("youtube"); assert hit==["YouTube"]
@pytest.mark.asyncio
async def test_invalid_numeric_rejected_when_inventory_available(monkeypatch):
    engine=BrowserEngine(); session=engine._register_session(BrowserSession("opera-gx-1","opera gx","chromium","real_profile","native",pid=1)); engine._select_session(session)
    async def collect(_): return [{"index":1,"title":"A","window_hwnd":100,"window_pid":1,"window_tab_order":1}]
    monkeypatch.setattr(engine,"_native_collect_all_tabs",collect)
    with pytest.raises(Exception) as exc: await engine.switch_tab(4)
    assert "tab 4 doesn't exist" in str(exc.value)
class B:
    is_started=False
    def __init__(self): self.calls=[]
    async def ensure_native_browser_session(self,*,browser=""): self.calls.append(("ensure",browser)); return object()
    async def close_tab(self,tab=None): self.calls.append(("close_tab",tab)); return R("closed")
class L:
    provider=None; model="fake"
    async def run(self,*a,**k): raise AssertionError("AI")
class A:
    def __init__(self): self.browser=B(); self.loop=L(); self.events=None
@pytest.mark.asyncio
async def test_close_youtube_tab_deterministic():
    a=A(); s=ConversationSession(a); await s.ask("close youtube tab")
    assert a.browser.calls==[("ensure",""),("close_tab","youtube")]
def test_version():
    assert 'version = "3.1.8"' in (Path(__file__).resolve().parents[1]/"pyproject.toml").read_text()
