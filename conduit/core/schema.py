"""Portable JSON-schema normalization for provider tool declarations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

# Gemini function schemas accept a useful JSON Schema subset but reject several
# keys commonly emitted by Pydantic/OpenAI schemas. Keeping the conversion here
# prevents provider-specific details leaking into the tool registry.
_GEMINI_UNSUPPORTED_KEYS = {
    "$schema",
    "$defs",
    "definitions",
    "additionalProperties",
    "additional_properties",
    "examples",
    "default",
    "title",
}


def normalize_json_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return a conservative provider-portable JSON schema copy.

    Unsupported schema metadata is removed, but user-defined property names such
    as ``title`` are preserved inside a ``properties`` mapping.
    """

    def clean(value: Any, *, inside_properties: bool = False) -> Any:
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for key, child in value.items():
                key_text = str(key)
                if not inside_properties and key_text in _GEMINI_UNSUPPORTED_KEYS:
                    continue
                result[key_text] = clean(
                    child,
                    inside_properties=(key_text == "properties"),
                )
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        return deepcopy(value)

    normalized = clean(schema)
    if normalized.get("type") != "object":
        normalized = {
            "type": "object",
            "properties": {"value": normalized},
            "required": ["value"],
        }
    normalized.setdefault("properties", {})
    return normalized


def gemini_tool_dict(name: str, description: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    """Create a current Gemini function declaration dictionary."""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": normalize_json_schema(schema),
    }


def ollama_tool_dict(name: str, description: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    """Create an Ollama/OpenAI-style function declaration dictionary."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": normalize_json_schema(schema),
        },
    }
