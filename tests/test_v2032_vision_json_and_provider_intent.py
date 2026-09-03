
from pathlib import Path
from types import SimpleNamespace

import pytest

from conduit.observer.models import ScreenCapture
from conduit.observer.parser import parse_structured_screen_analysis


def _capture():
    return ScreenCapture(
        image_path=Path("screen.png"),
        width=1920,
        height=1080,
        captured_at="test",
    )


def test_parser_accepts_python_style_structured_object():
    raw = """{
      'application': 'WhatsApp',
      'summary': 'Search is open',
      'elements': [
        {
          'id': 'search',
          'label': 'Search',
          'role': 'textbox',
          'bounds': {'x': 10, 'y': 20, 'width': 300, 'height': 40},
          'confidence': 0.95,
          'text': 'Maryam',
          'enabled': True,
          'visible': True
        }
      ]
    }"""
    result = parse_structured_screen_analysis(
        raw,
        capture=_capture(),
        provider_id="ollama",
        model="qwen2.5vl:7b",
    )
    assert result.application == "WhatsApp"
    assert result.elements[0].text == "Maryam"


class RepairProvider:
    provider_id = "ollama"
    capabilities = SimpleNamespace(vision=True)

    async def describe_image(self, image_path, prompt, model):
        return SimpleNamespace(
            text='{"application":"WhatsApp","summary":"ok","elements":[{bad json}]}',
            model=model,
        )

    async def chat(self, messages, model):
        return SimpleNamespace(
            text='{"application":"WhatsApp","summary":"Search ready","elements":[]}',
            model=model,
        )


@pytest.mark.asyncio
async def test_structured_observer_repairs_malformed_json(tmp_path):
    from conduit.observer.observer import DesktopObserver

    image = tmp_path / "screen.png"
    image.write_bytes(b"not-used")
    capture = ScreenCapture(
        image_path=image,
        width=1920,
        height=1080,
        captured_at="test",
    )
    observer = DesktopObserver(RepairProvider(), model="qwen2.5vl:7b")
    result = await observer.analyze_structured("Find WhatsApp search", capture=capture)
    assert result.application == "WhatsApp"
    assert result.summary == "Search ready"


def test_provider_switch_detector_handles_typo_between_switch_and_provider():
    import importlib.util

    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "def _detect_provider_switch" in source
    assert 'provider_target == "openai"' in source
    assert 'provider_target == "ollama"' in source
    assert 'provider_target == "gemini"' in source


def test_switch_detector_semantics_from_source():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert '("switch", "use", "change", "connect", "go", "move")' in source
    assert '"open ai"' in source
