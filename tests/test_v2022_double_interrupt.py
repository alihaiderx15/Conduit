
from pathlib import Path


def test_shell_has_persistent_sigint_handler():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "def handle_sigint" in source
    assert 'state["active_task"] = active_task' in source
    assert 'state["active_task"] = None' in source
    assert "signal.signal(signal.SIGINT, handle_sigint)" in source


def test_idle_ctrl_c_is_swallowed():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "Ready. I'm listening." in source
    assert "A stray SIGINT must never unwind the top-level chat loop." in source


def test_repeated_interrupt_is_idempotent():
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert 'if not state.get("interrupt_requested", False):' in source
    assert 'state["interrupt_requested"] = True' in source
