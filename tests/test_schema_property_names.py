
from conduit.core.schema import normalize_json_schema
from conduit.tools.builtin import registry


def test_schema_preserves_title_property_name():
    schema = normalize_json_schema({
        "type": "object",
        "properties": {"title": {"type": "string", "title": "UI label"}},
        "required": ["title"],
    })
    assert "title" in schema["properties"]
    assert "title" not in schema["properties"]["title"]


def test_window_tool_schemas_accept_title_and_handle():
    activate = registry.get("system.activate_window").parameters
    state = registry.get("system.window_state").parameters
    assert set(activate["properties"]) == {"title", "handle"}
    assert {"title", "handle", "state"} <= set(state["properties"])
