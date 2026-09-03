
from types import SimpleNamespace

import pytest

from conduit.conversation import ConversationSession


class Events:
    def __init__(self):
        self.names = []
    async def emit(self, name, **kwargs):
        self.names.append(name)


class Agent:
    def __init__(self):
        self.events = Events()
        self.loop = SimpleNamespace(provider=None, model="fake")


@pytest.mark.asyncio
async def test_interrupt_broadcasts_conversation_and_speech_stop():
    agent = Agent()
    session = ConversationSession(agent)
    await session.interrupt()
    assert "conversation.interrupted" in agent.events.names
    assert "speech.stop" in agent.events.names


def test_most_popular_lookup_is_bounded():
    import conduit.capabilities.youtube_structured as ys
    source = open(ys.__file__, encoding="utf-8").read()
    block = source[source.index("def most_popular_upload"):source.index("def play_most_popular_visible")]
    assert "_video_from_channel_sort_chip" in block
    assert '"Popular"' in block
    assert "sort=p" not in block
    assert "_channel_video_entries(channel, limit=None)" not in block


def test_tool_executor_runs_sync_tools_off_event_loop():
    import conduit.execution.executor as executor
    source = open(executor.__file__, encoding="utf-8").read()
    assert "asyncio.to_thread(item.handler" in source


def test_chat_shell_has_task_interrupt():
    from pathlib import Path
    shell = Path(__file__).resolve().parents[1] / "scripts" / "conduit_chat.py"
    source = shell.read_text(encoding="utf-8")
    assert "task.cancel" in source
    assert "Interrupted. I'm listening." in source
    assert "def handle_sigint" in source
