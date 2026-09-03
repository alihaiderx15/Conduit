from pathlib import Path

import pytest
from PIL import Image

from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.desktop.controller import DesktopController
from conduit.desktop.models import Point, ScreenBounds
from conduit.observer import (
    DesktopCaptureService,
    DesktopObserver,
    ObserveActWorkflow,
    ScreenLocator,
    compare_screen_states,
    parse_structured_screen_analysis,
)
from conduit.providers.base import AIProvider


class FakeCaptureBackend:
    def capture(self, destination: Path) -> tuple[int, int]:
        Image.new("RGB", (800, 600)).save(destination)
        return 800, 600


class FakeVisionProvider(AIProvider):
    provider_id = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(vision=True)

    async def list_models(self): return ["vision"]
    async def chat(self, messages, *, model, tools=()): return ProviderResponse(text="")

    async def describe_image(self, image_path, prompt, *, model):
        return ProviderResponse(text=self.responses.pop(0), model=model)


class FakeDesktopBackend:
    def __init__(self) -> None:
        self.clicked = None
    def screen_bounds(self): return ScreenBounds(800, 600)
    def mouse_position(self): return Point(0, 0)
    def move_to(self, x, y, duration): pass
    def click(self, x, y, clicks, interval, button): self.clicked = (x, y, clicks, button)
    def write(self, text, interval): pass
    def press(self, key, presses, interval): pass
    def hotkey(self, *keys): pass
    def scroll(self, amount): pass


def make_capture(tmp_path):
    return DesktopCaptureService(FakeCaptureBackend()).capture(tmp_path / "screen.png")


def test_parser_validates_and_skips_out_of_bounds(tmp_path):
    capture = make_capture(tmp_path)
    text = '''{
      "application":"Notepad",
      "summary":"A blank document",
      "elements":[
        {"id":"editor","label":"Text area","role":"textbox","bounds":{"x":100,"y":100,"width":400,"height":300},"confidence":0.96},
        {"id":"bad","label":"Bad","role":"button","bounds":{"x":900,"y":0,"width":20,"height":20},"confidence":1.0}
      ]
    }'''
    analysis = parse_structured_screen_analysis(text, capture=capture, provider_id="fake", model="vision")
    assert analysis.application == "Notepad"
    assert len(analysis.elements) == 1
    assert analysis.elements[0].center == (300, 250)


def test_locator_finds_best_match(tmp_path):
    capture = make_capture(tmp_path)
    analysis = parse_structured_screen_analysis(
        '{"application":"Browser","summary":"","elements":['
        '{"id":"search_box","label":"YouTube Search","role":"textbox","bounds":{"x":10,"y":10,"width":200,"height":40},"confidence":0.99},'
        '{"id":"settings","label":"Settings","role":"button","bounds":{"x":300,"y":10,"width":50,"height":40},"confidence":0.9}]}'
        , capture=capture, provider_id="fake", model="vision"
    )
    target = ScreenLocator(analysis).find("search")
    assert target.element_id == "search_box"


def test_compare_states_reports_changes(tmp_path):
    capture = make_capture(tmp_path)
    before = parse_structured_screen_analysis(
        '{"application":"A","summary":"one","elements":[{"id":"old","label":"Old","role":"button","bounds":{"x":1,"y":1,"width":10,"height":10}}]}',
        capture=capture, provider_id="fake", model="vision"
    )
    after = parse_structured_screen_analysis(
        '{"application":"B","summary":"two","elements":[{"id":"new","label":"New","role":"button","bounds":{"x":1,"y":1,"width":10,"height":10}}]}',
        capture=capture, provider_id="fake", model="vision"
    )
    change = compare_screen_states(before, after)
    assert change.changed
    assert change.application_changed
    assert change.added == ("new",)
    assert change.removed == ("old",)


@pytest.mark.asyncio
async def test_observer_returns_structured_analysis(tmp_path):
    provider = FakeVisionProvider(['{"application":"Notepad","summary":"Visible","elements":[]}'])
    observer = DesktopObserver(provider, model="vision", capture_service=DesktopCaptureService(FakeCaptureBackend()))
    analysis = await observer.analyze_structured(capture=await observer.capture(tmp_path / "screen.png"))
    assert analysis.application == "Notepad"


@pytest.mark.asyncio
async def test_workflow_requires_approval_and_clicks_center(tmp_path):
    responses = [
        '{"application":"Notepad","summary":"Before","elements":[{"id":"editor","label":"Text area","role":"textbox","bounds":{"x":100,"y":100,"width":400,"height":300},"confidence":0.99}]}',
        '{"application":"Notepad","summary":"Focused","elements":[{"id":"editor","label":"Text area","role":"textbox","bounds":{"x":100,"y":100,"width":400,"height":300},"confidence":0.99}]}'
    ]
    observer = DesktopObserver(FakeVisionProvider(responses), model="vision", capture_service=DesktopCaptureService(FakeCaptureBackend()))
    backend = FakeDesktopBackend()
    workflow = ObserveActWorkflow(observer, DesktopController(backend))
    located = await workflow.locate("text area")
    with pytest.raises(PermissionError):
        await workflow.click_and_verify(located, approved=False)
    result = await workflow.click_and_verify(located, approved=True)
    assert backend.clicked[:2] == (300, 250)
    assert result.target.element_id == "editor"
