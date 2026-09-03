from pathlib import Path
import pytest
from conduit.conversation.session import ConversationSession


def root():
    return Path(__file__).resolve().parents[1]


def test_user_prompt_goes_to_chat_immediately():
    src=(root()/"conduit/gui/app.py").read_text(encoding="utf-8")
    block=src[src.index("    def _send_command"):src.index("    def _quick_command")]
    assert "self.chat.add_user(text)" in block


def test_runtime_only_appends_conduit_reply():
    src=(root()/"conduit/gui/app.py").read_text(encoding="utf-8")
    block=src[src.index("    def _runtime_answer"):src.index("    def _runtime_error")]
    assert "self.chat.add_conduit(answer, success)" in block
    assert "add_turn(user" not in block


def test_user_prompt_is_also_mirrored_to_programmer_console():
    src=(root()/"conduit/gui/runtime.py").read_text(encoding="utf-8")
    assert 'self.signals.console.emit("USER", command)' in src


def test_file_explorer_is_system_request():
    for phrase in ("open file explorer", "open the file explorer", "launch Windows File Explorer"):
        assert ConversationSession._could_be_system_control_request(phrase)


@pytest.mark.asyncio
async def test_file_explorer_passes_required_app_argument():
    class Tools:
        def __init__(self): self.calls=[]
        async def execute(self, call, *, confirmed=False):
            self.calls.append((call.name, dict(call.arguments), confirmed))
            class Result:
                success=True
                message="Opened file explorer."
            return Result()
    class Agent:
        def __init__(self): self.tools=Tools()
    session=object.__new__(ConversationSession)
    session.agent=Agent()
    result=await session._execute_system_control_request("open file explorer")
    assert result is not None
    assert session.agent.tools.calls == [("system.open_app", {"app":"file explorer"}, True)]


def test_version_252():
    assert 'version = "3.1.8"' in (root()/"pyproject.toml").read_text(encoding="utf-8")
