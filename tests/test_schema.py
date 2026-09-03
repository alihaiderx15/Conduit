from conduit.core.schema import gemini_tool_dict, normalize_json_schema


def test_normalizer_removes_provider_incompatible_keys() -> None:
    schema = {
        "type": "object",
        "title": "Example",
        "properties": {
            "path": {
                "type": "string",
                "default": "x",
                "description": "Target path",
            }
        },
        "additionalProperties": False,
        "required": ["path"],
    }
    result = normalize_json_schema(schema)
    assert "additionalProperties" not in result
    assert "title" not in result
    assert "default" not in result["properties"]["path"]
    assert result["required"] == ["path"]


def test_gemini_declaration_uses_current_shape() -> None:
    declaration = gemini_tool_dict(
        "open_app",
        "Open an application",
        {"type": "object", "properties": {"name": {"type": "string"}}},
    )
    assert declaration["type"] == "function"
    assert declaration["name"] == "open_app"
    assert "function" not in declaration
