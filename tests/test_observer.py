from pathlib import Path

import pytest
from PIL import Image

from conduit.core.models import ProviderCapabilities, ProviderResponse
from conduit.observer import DesktopCaptureService, DesktopObserver
from conduit.providers.base import AIProvider


class FakeBackend:
    def capture(self, destination: Path) -> tuple[int, int]:
        Image.new("RGB", (320, 200)).save(destination)
        return 320, 200


class FakeVisionProvider(AIProvider):
    provider_id = "fake"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(vision=True)

    async def list_models(self) -> list[str]:
        return ["vision-test"]

    async def chat(self, messages, *, model, tools=()):
        return ProviderResponse(text="unused", model=model)

    async def describe_image(self, image_path, prompt, *, model):
        assert image_path.exists()
        return ProviderResponse(text="A test desktop is visible.", model=model)


class FakeTextProvider(FakeVisionProvider):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(vision=False)


@pytest.mark.asyncio
async def test_capture_service_creates_image(tmp_path):
    path = tmp_path / "screen.png"
    service = DesktopCaptureService(FakeBackend())
    capture = service.capture(path)
    assert capture.image_path == path
    assert capture.width == 320
    assert capture.height == 200
    assert path.is_file()


@pytest.mark.asyncio
async def test_observer_analyzes_capture(tmp_path):
    service = DesktopCaptureService(FakeBackend())
    observer = DesktopObserver(
        FakeVisionProvider(), model="vision-test", capture_service=service
    )
    capture = await observer.capture(tmp_path / "screen.png")
    analysis = await observer.analyze("What is visible?", capture=capture)
    assert analysis.description == "A test desktop is visible."
    assert analysis.provider_id == "fake"


@pytest.mark.asyncio
async def test_observer_rejects_text_only_provider():
    observer = DesktopObserver(FakeTextProvider(), model="text-test")
    with pytest.raises(Exception, match="does not support images"):
        await observer.analyze()
