from pathlib import Path
import pytest

from conduit.actions import ActionDescriptor, UnifiedActionRegistry, register_default_actions
from conduit.planning import StepCapability
from conduit.tools import ToolRisk
from conduit.tools.builtin import registry as builtin_registry
from conduit.execution import ToolExecutor
from conduit.core.models import ToolCall


def test_registry_combines_tools_and_engines():
    actions = register_default_actions(UnifiedActionRegistry(builtin_registry))
    assert "files.search" in actions
    assert "browser.goto" in actions
    assert "desktop.click" in actions
    assert actions.get("files.write_text").risk is ToolRisk.CONFIRM
    assert actions.get("browser.goto").engine is StepCapability.BROWSER


def test_planning_capabilities_preserve_confirmation():
    actions = register_default_actions(UnifiedActionRegistry(builtin_registry))
    by_name = {item.name: item for item in actions.planning_capabilities()}
    assert by_name["files.write_text"].requires_confirmation is True
    assert by_name["files.exists"].requires_confirmation is False


def test_duplicate_unified_action_rejected():
    actions = UnifiedActionRegistry(builtin_registry)
    with pytest.raises(ValueError):
        actions.register(ActionDescriptor("files.exists", StepCapability.TOOL, "duplicate"))


@pytest.mark.asyncio
async def test_safe_file_actions_and_confirmed_write(tmp_path: Path):
    executor = ToolExecutor(builtin_registry)
    target = tmp_path / "note.txt"
    pending = await executor.execute(ToolCall("files.write_text", {"path": str(target), "text": "hello"}))
    assert not hasattr(pending, "success")
    written = await executor.execute(ToolCall("files.write_text", {"path": str(target), "text": "hello"}), confirmed=True)
    assert written.success
    checked = await executor.execute(ToolCall("files.exists", {"path": str(target)}))
    assert checked.success and checked.data["exists"] is True
    read = await executor.execute(ToolCall("files.read_text", {"path": str(target)}))
    assert read.data["text"] == "hello"


def test_files_read_text_exposes_text_and_content_alias(tmp_path):
    from conduit.tools.builtin import registry

    target = tmp_path / "sample.txt"
    target.write_text("hello conduit", encoding="utf-8")
    result = registry.get("files.read_text").handler(path=str(target))

    assert result.success is True
    assert result.data["text"] == "hello conduit"
    assert result.data["content"] == "hello conduit"
