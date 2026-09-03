
from pathlib import Path
from types import SimpleNamespace
import os

from conduit.memory.session import ShortTermSessionMemory, SessionTurn
from conduit.conversation.session import ConversationSession


def test_temp_store_keeps_exact_history_without_duplicate_ram_list(tmp_path):
    memory = ShortTermSessionMemory(
        temp_dir=tmp_path,
        recent_cache_turns=4,
        recent_cache_events=4,
    )
    for i in range(20):
        memory.add(f"user {i}", f"assistant {i}")

    assert len(memory) == 20
    assert len(memory._recent_turns) == 4
    assert memory.turn_at(0) == SessionTurn("user 0", "assistant 0")
    assert memory.turn_at(19) == SessionTurn("user 19", "assistant 19")
    assert memory.turn_at(-1) == SessionTurn("user 19", "assistant 19")
    assert memory.path.exists()
    memory.close()
    assert not memory.path.exists()


def test_history_proxy_is_list_like_but_backed_by_store(tmp_path):
    memory = ShortTermSessionMemory(temp_dir=tmp_path)
    memory.history.append(SimpleNamespace(user="hello", assistant="hi"))
    memory.history.extend([
        SimpleNamespace(user="second", assistant="two"),
        SimpleNamespace(user="third", assistant="three"),
    ])
    assert len(memory.history) == 3
    assert memory.history[0].user == "hello"
    assert memory.history[-1].assistant == "three"
    assert [x.user for x in memory.history[-2:]] == ["second", "third"]
    memory.close()


def test_clear_wipes_exact_session_but_keeps_store_reusable(tmp_path):
    memory = ShortTermSessionMemory(temp_dir=tmp_path)
    memory.add("one", "1")
    memory.add_event("tool.completed", '{"tool":"x"}')
    memory.clear()
    assert len(memory) == 0
    assert memory.event_count() == 0
    assert memory.path.exists()
    memory.add("new", "answer")
    assert memory.turn_at(0).user == "new"
    memory.close()


def test_context_retrieves_relevant_old_turn_from_disk(tmp_path):
    memory = ShortTermSessionMemory(temp_dir=tmp_path, recent_cache_turns=4)
    memory.add("my secret project codename is nebula", "I will remember it this session.")
    for i in range(30):
        memory.add(f"ordinary message {i}", f"ordinary answer {i}")
    context = memory.context_for(
        "what was the nebula project codename",
        recent_turns=4,
        relevant_older=4,
    )
    assert "nebula" in context.casefold()
    assert len(memory._recent_turns) <= 4
    memory.close()


def make_recall_session(tmp_path):
    session = object.__new__(ConversationSession)
    session.session_memory = ShortTermSessionMemory(temp_dir=tmp_path)
    session.history = session.session_memory.history
    return session


def test_deterministic_first_message_recall(tmp_path):
    session = make_recall_session(tmp_path)
    session.session_memory.add("open discord", "Opened Discord.")
    session.session_memory.add("open youtube", "Opened YouTube.")
    answer = session._session_recall_answer(
        "what did I ask you first in the conversation?"
    )
    assert answer == (
        "Your first message in this conversation was: open discord"
    )
    session.session_memory.close()


def test_deterministic_second_and_reply_recall(tmp_path):
    session = make_recall_session(tmp_path)
    session.session_memory.add("first request", "first answer")
    session.session_memory.add("second request", "second answer")
    answer = session._session_recall_answer("what was my second request?")
    assert "second request" in answer
    reply = session._session_recall_answer(
        "what did you answer to my first question?"
    )
    assert "first answer" in reply
    session.session_memory.close()


def test_history_detector_knows_conversation_questions():
    assert ConversationSession._message_needs_history(
        "what did we talk about earlier in this conversation?"
    )
    assert ConversationSession._message_needs_history(
        "what was my first question?"
    )


def test_only_one_canonical_turn_write_in_source():
    root = Path(__file__).resolve().parents[1]
    source = (root/"conduit/conversation/session.py").read_text(encoding="utf-8")
    remember = source[source.index("def _remember_turn"):source.index("def _history_text")]
    assert "self.session_memory.add(user, assistant)" in remember
    assert "self.history.append(" not in remember


def test_version_301():
    root = Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
