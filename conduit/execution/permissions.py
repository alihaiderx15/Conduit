from dataclasses import dataclass
from enum import Enum
from conduit.tools.models import RegisteredTool, ToolRisk
class PermissionDecision(str, Enum):
    ALLOW="allow"; REQUIRE_CONFIRMATION="require_confirmation"; DENY="deny"
@dataclass(slots=True)
class PermissionManager:
    def evaluate(self, item: RegisteredTool) -> PermissionDecision:
        return PermissionDecision.ALLOW if item.risk is ToolRisk.SAFE else PermissionDecision.REQUIRE_CONFIRMATION
