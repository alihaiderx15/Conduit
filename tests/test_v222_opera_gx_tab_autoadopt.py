
from pathlib import Path
import inspect
import pytest
from conduit.browser import sessions as bs
from conduit.conversation import ConversationSession

def test_opera_gx_family_match():
    src=inspect.getsource(bs.browser_windows_by_executable)
    assert '"\\\\opera gx\\\\" in actual_norm' in src

class R:
    def __init__(self,message="ok",data=None): self.message=message; self.data=data or {}; self.success=True
class B:
    is_started=False
    def __init__(self): self.calls=[]
    async def ensure_native_browser_session(self,*,browser=""): self.calls.append(("ensure",browser)); return object()
    async def switch_tab(self,tab): self.calls.append(("switch_tab",tab)); return R("switched")
    async def new_tab_focus_only(self,*,browser=""): self.calls.append(("new_tab_focus_only",browser)); return R("new")
class L:
    provider=None; model="fake"
    async def run(self,*a,**k): raise AssertionError("AI")
class A:
    def __init__(self): self.browser=B(); self.loop=L(); self.events=None

@pytest.mark.asyncio
async def test_switch_to_tab_1_autoadopts():
    a=A(); s=ConversationSession(a); await s.ask("switch to tab 1")
    assert a.browser.calls == [("ensure",""),("switch_tab",1)]

@pytest.mark.asyncio
async def test_switch_to_youtube_tab_autoadopts():
    a=A(); s=ConversationSession(a); await s.ask("switch to youtube tab")
    assert a.browser.calls == [("ensure",""),("switch_tab","youtube")]

def test_version():
    assert 'version = "3.1.8"' in (Path(__file__).resolve().parents[1]/"pyproject.toml").read_text()
