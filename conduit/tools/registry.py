from __future__ import annotations
from typing import Any, Mapping
from conduit.core.models import ToolDefinition
from conduit.core.schema import normalize_json_schema
from .errors import DuplicateToolError, ToolNotFoundError
from .models import RegisteredTool, ToolHandler, ToolRisk

class ToolRegistry:
    def __init__(self) -> None: self._tools: dict[str, RegisteredTool] = {}
    def register(self, item: RegisteredTool) -> RegisteredTool:
        name=item.name.strip()
        if not name: raise ValueError("Tool name cannot be empty.")
        if name in self._tools: raise DuplicateToolError(f"Tool '{name}' is already registered.")
        self._tools[name]=item
        return item
    def get(self, name: str) -> RegisteredTool:
        try: return self._tools[name]
        except KeyError as exc: raise ToolNotFoundError(f"Tool '{name}' is not registered.") from exc
    def all(self) -> tuple[RegisteredTool, ...]: return tuple(self._tools.values())
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(ToolDefinition(x.name,x.description,x.parameters) for x in self._tools.values())
    def __len__(self)->int: return len(self._tools)

def tool(registry: ToolRegistry, *, name: str, description: str,
         parameters: Mapping[str, Any] | None=None, risk: ToolRisk=ToolRisk.SAFE):
    schema=normalize_json_schema(parameters or {"type":"object","properties":{}})
    def decorator(handler: ToolHandler) -> ToolHandler:
        registry.register(RegisteredTool(name,description.strip(),schema,risk,handler))
        return handler
    return decorator
