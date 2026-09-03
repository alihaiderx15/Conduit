
from pathlib import Path


def test_ollama_download_is_background_task_not_awaited_inline():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")

    start = source.index("async def _handle_ollama_download")
    end = source.index("async def _watch_ollama_download", start)
    handler = source[start:end]

    assert "subprocess.Popen(" in handler
    assert "asyncio.create_task(" in handler
    assert "process.wait" not in handler
    assert "self.signals.busy.emit(True)" not in handler


def test_background_watcher_waits_without_blocking_event_loop():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    start = source.index("async def _watch_ollama_download")
    end = source.index("@staticmethod", start)
    watcher = source[start:end]
    assert "await asyncio.to_thread(process.wait)" in watcher
    assert "available in the Ollama model selector" in watcher


def test_gui_asks_gemini_or_cancel_after_download_starts():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/app.py").read_text(encoding="utf-8")
    assert "Conduit remains usable" in source
    assert 'box.addButton("Switch to Gemini"' in source
    assert 'box.addButton("Cancel Task"' in source
    assert "The Ollama download will continue either way." in source


def test_download_completion_does_not_auto_switch_model():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    start = source.index("async def _watch_ollama_download")
    end = source.index("@staticmethod", start)
    watcher = source[start:end]
    assert "_handle_ollama_switch" not in watcher
