
import inspect
import pytest

from conduit.browser.engine import BrowserEngine
from conduit.browser.sessions import BrowserSession


def test_collect_all_tabs_prefers_background_uia():
    src = inspect.getsource(BrowserEngine._native_collect_all_tabs)
    assert "_native_uia_tabs_for_window" in src
    assert "_native_collect_tabs_for_window" in src  # compatibility fallback


@pytest.mark.asyncio
async def test_background_inventory_does_not_call_visible_scanner_when_uia_works(monkeypatch):
    engine = BrowserEngine()
    session = engine._register_session(BrowserSession(
        "opera-gx-1", "opera gx", "chromium", "real_profile", "native", pid=1
    ))
    engine._select_session(session)

    monkeypatch.setattr(
        "conduit.browser.engine.browser_windows_by_executable",
        lambda _: [(100, 1)],
    )
    monkeypatch.setattr(
        engine,
        "_native_uia_tabs_for_window",
        lambda *_: [
            {"title": "GX Corner - Opera", "url": "", "window_hwnd": 100,
             "window_pid": 1, "window_tab_order": 1, "active": False},
            {"title": "(149) YouTube - Opera", "url": "", "window_hwnd": 100,
             "window_pid": 1, "window_tab_order": 2, "active": True},
        ],
    )

    async def visible_scanner(*args, **kwargs):
        raise AssertionError("visible scanner must not run when UIA inventory succeeds")

    monkeypatch.setattr(engine, "_native_collect_tabs_for_window", visible_scanner)
    tabs = await engine._native_collect_all_tabs(session)
    assert [x["title"] for x in tabs] == ["GX Corner - Opera", "(149) YouTube - Opera"]


@pytest.mark.asyncio
async def test_named_switch_prefers_exact_title_match_over_bad_url_alias(monkeypatch):
    engine = BrowserEngine()
    session = engine._register_session(BrowserSession(
        "opera-gx-1", "opera gx", "chromium", "real_profile", "native", pid=1
    ))
    engine._select_session(session)

    # Reproduce v2.2.5 failure: tab 1 accidentally carries a YouTube URL,
    # while the real YouTube tab is tab 3 by title.
    tabs = [
        {"index": 1, "title": "GX Corner - Opera", "url": "https://youtube.com/stale",
         "window_hwnd": 100, "window_pid": 1, "window_tab_order": 1},
        {"index": 2, "title": "Conduit v2.0.41 Test - Opera", "url": "",
         "window_hwnd": 100, "window_pid": 1, "window_tab_order": 2},
        {"index": 3, "title": "(149) YouTube - Opera", "url": "https://youtube.com/",
         "window_hwnd": 100, "window_pid": 1, "window_tab_order": 3},
    ]
    activated = []

    async def collect(_): return tabs
    async def activate(_, item): activated.append(item["index"])
    async def state(**kwargs):
        from conduit.browser.models import BrowserState
        return BrowserState("(149) YouTube - Opera", "", "", 0, 0)

    monkeypatch.setattr(engine, "_native_collect_all_tabs", collect)
    monkeypatch.setattr(engine, "_native_activate_inventory_tab", activate)
    monkeypatch.setattr(engine, "state", state)

    result = await engine.switch_tab("youtube")
    assert activated == [3]
    assert "YouTube" in result.message


def test_version_is_226():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    assert 'version = "3.1.8"' in text
