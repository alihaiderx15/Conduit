from pathlib import Path

import pytest

from conduit.browser import BrowserEngine, BrowserNotStartedError, BrowserTarget, TargetKind
from conduit.events import EventBus


pytestmark = pytest.mark.asyncio


async def test_browser_requires_start():
    engine = BrowserEngine(headless=True)
    with pytest.raises(BrowserNotStartedError):
        await engine.state()


async def test_url_normalization():
    assert BrowserEngine._normalize_url("example.com") == "https://example.com"
    assert BrowserEngine._normalize_url("file:///tmp/x") == "file:///tmp/x"


async def test_local_page_semantic_actions():
    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("Playwright not installed")

    page_path = Path(__file__).parent / "fixtures" / "browser_test_page.html"
    events = EventBus()
    seen = []
    events.subscribe("browser.*", lambda event: seen.append(event.name))
    engine = BrowserEngine(event_bus=events, headless=True)
    try:
        try:
            await engine.start()
        except Exception as exc:
            if "Executable doesn't exist" in str(exc) or "playwright install" in str(exc):
                pytest.skip("Chromium browser binary not installed")
            raise
        await engine.goto(page_path.resolve().as_uri())
        field = BrowserTarget(TargetKind.LABEL, "Search query")
        submit = BrowserTarget(TargetKind.ROLE, "button", name="Submit")
        await engine.fill(field, "Apex Legends")
        await engine.click(submit)
        state = await engine.state()
        assert state.title == "Conduit Browser Test"
        assert "Submitted: Apex Legends" in state.visible_text
        assert "browser.action.started" in seen
        assert "browser.action.completed" in seen
    finally:
        await engine.close()
