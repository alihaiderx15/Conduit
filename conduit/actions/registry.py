"""One registry describing every action visible to Conduit's agents."""
from __future__ import annotations
from conduit.planning import PlanningCapability, StepCapability
from conduit.tools import ToolRegistry, ToolRisk
from .models import ActionDescriptor

class UnifiedActionRegistry:
    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._actions: dict[str, ActionDescriptor] = {}
        for item in tool_registry.all():
            self.register(ActionDescriptor(item.name, StepCapability.TOOL, item.description, item.parameters, item.risk))

    def register(self, action: ActionDescriptor) -> ActionDescriptor:
        if action.name in self._actions:
            raise ValueError(f"Action '{action.name}' is already registered.")
        self._actions[action.name] = action
        return action

    def get(self, name: str) -> ActionDescriptor:
        try:
            return self._actions[name]
        except KeyError as exc:
            raise KeyError(f"Action '{name}' is not registered.") from exc

    def all(self) -> tuple[ActionDescriptor, ...]:
        return tuple(self._actions.values())

    def planning_capabilities(self) -> tuple[PlanningCapability, ...]:
        return tuple(
            PlanningCapability(
                item.name,
                item.engine,
                item.description,
                _schema_summary(item.parameters),
                item.requires_confirmation,
            )
            for item in self._actions.values()
        )

    def __contains__(self, name: str) -> bool:
        return name in self._actions

    def __len__(self) -> int:
        return len(self._actions)


def _schema_summary(schema: object) -> dict[str, str]:
    if not isinstance(schema, dict):
        return {}
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    result: dict[str, str] = {}
    required = set(schema.get("required", []))
    for name, definition in properties.items():
        kind = definition.get("type", "value") if isinstance(definition, dict) else "value"
        result[str(name)] = str(kind) if name in required else f"optional {kind}"
    return result
