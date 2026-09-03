
from pathlib import Path
from conduit.conversation.command_aliases import normalize_conversation_command
from conduit.memory import MemoryManager
from conduit.memory.learning import LongTermMemoryLearner

def test_aliases():
    assert normalize_conversation_command("clear short term memory") == "/clear"
    assert normalize_conversation_command("show conversation history") == "/history"
    assert normalize_conversation_command("list available actions") == "/actions"
    assert normalize_conversation_command("what provider are you using") == "/provider"
    assert normalize_conversation_command("switch to gemini") == "/switch gemini"
    assert normalize_conversation_command("use ollama") == "/switch ollama"
    assert normalize_conversation_command("switch to open ai") == "/switch openai"
    assert normalize_conversation_command("close conduit") == "/exit"

def test_persistent_code_path(tmp_path):
    db=tmp_path/"m.sqlite3"
    m=MemoryManager(db)
    result=LongTermMemoryLearner(m).remember_explicit_directive(r"always save the generated code files in G:\CONDUIT\\")
    assert result == {"scope":"code","key":"output_directory","value":"G:\\CONDUIT\\"}
    m.close()
    m=MemoryManager(db)
    assert m.directive("code","output_directory")=="G:\\CONDUIT\\"
    m.close()

def test_intercept_order():
    root=Path(__file__).resolve().parents[1]
    src=(root/"conduit/conversation/session.py").read_text(encoding="utf-8")
    assert src.index("remember_explicit_directive(original_clean)") < src.index("needs_history = self._message_needs_history(clean)")

def test_version():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
