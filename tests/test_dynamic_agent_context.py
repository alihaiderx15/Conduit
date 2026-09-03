from __future__ import annotations

import pytest

from conduit.dynamic_agent import AgentContext, AgentObservation, VariableResolutionError, VariableStore


def test_variable_store_resolves_exact_and_embedded_references():
    store = VariableStore({"page": {"url": "https://example.test", "count": 3}})
    assert store.resolve("{{page.url}}") == "https://example.test"
    assert store.resolve("Found {{page.count}} items") == "Found 3 items"
    assert store.resolve({"url": "{{page.url}}", "items": ["{{page.count}}"]}) == {
        "url": "https://example.test",
        "items": [3],
    }


def test_missing_variable_raises_clear_error():
    store = VariableStore()
    with pytest.raises(VariableResolutionError, match="Unknown context variable"):
        store.resolve("{{missing}}")


def test_context_captures_named_values_from_observation():
    context = AgentContext("Inspect page")
    observation = AgentObservation(
        iteration=1,
        action="browser.read_page",
        arguments={},
        success=True,
        message="Read page",
        data={"title": "Conduit Test", "url": "https://example.test"},
    )
    context.add_observation(
        observation,
        captures={"page_title": "data.title", "page_url": "data.url"},
    )

    assert context.store.get("page_title") == "Conduit Test"
    assert context.store.get("page_url") == "https://example.test"
    assert context.store.get("last.data.title") == "Conduit Test"
    assert context.store.get("step_1.success") is True


def test_context_snapshot_does_not_expose_metadata_wrappers():
    context = AgentContext("Goal", {"seed": "value"})
    assert context.variables == {"seed": "value"}
    assert context.store.metadata()["seed"]["source"] == "initial"


def test_missing_optional_capture_does_not_crash_successful_observation():
    context = AgentContext("Read a file")
    observation = AgentObservation(
        iteration=1,
        action="files.read_text",
        arguments={"path": "example.txt"},
        success=True,
        message="Read example.txt.",
        data={"text": "hello"},
    )

    context.add_observation(
        observation,
        captures={"file_content": "data.content"},
    )

    assert context.store.get("last.success") is True
    assert context.store.get("file_content", None) is None
    warnings = context.store.get("last_capture_warnings")
    assert warnings[0]["name"] == "file_content"
    assert warnings[0]["path"] == "data.content"
