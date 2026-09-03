from pathlib import Path
from conduit.conversation.code_planner import parse_code_intent
from conduit.code_helper import code_service

def test_snake_game_routes():
    x=parse_code_intent("generate a python snake game",has_active_code=False)
    assert x and x.action=="generate" and x.language=="python"

def test_code_shorthand_routes():
    x=parse_code_intent("code that prints hello world in C++",has_active_code=False)
    assert x and x.action=="generate" and x.language=="cpp"

def test_python_validation():
    assert code_service.validate_source('print("hello")',language="python")[0]
    assert not code_service.validate_source('print("hello"',language="python")[0]

def test_fence_cleanup():
    fenced="""```python
print("hello")
```"""
    assert code_service.validate_source(fenced,language="python")[0]

def test_timeout_and_repair_present():
    root=Path(__file__).resolve().parents[1]
    src=(root/"conduit/conversation/session.py").read_text(encoding="utf-8")
    assert "run_with_progress_watchdog" in src
    assert "watchdog_interval_seconds=60" in src
    assert "repair_attempt < 2" in src
    assert "generation_validated" in src
    assert "provider_request" in src

def test_tool_rejects_empty():
    root=Path(__file__).resolve().parents[1]
    src=(root/"conduit/tools/builtin.py").read_text(encoding="utf-8")
    assert "Refusing to create an empty code file." in src

def test_version():
    root=Path(__file__).resolve().parents[1]
    assert 'version = "3.1.8"' in (root/"pyproject.toml").read_text(encoding="utf-8")
