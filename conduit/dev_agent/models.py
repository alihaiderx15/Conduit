
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class ProjectKind(StrEnum):
    PYTHON = "python"
    NODE = "node"
    STATIC_WEB = "static_web"
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    UNKNOWN = "unknown"


class DevErrorCategory(StrEnum):
    NONE = "none"
    SYNTAX_ERROR = "syntax_error"
    DEPENDENCY_MISSING = "dependency_missing"
    COMPILATION_ERROR = "compilation_error"
    RUNTIME_ERROR = "runtime_error"
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    ENTRY_POINT_MISSING = "entry_point_missing"
    BUILD_TOOL_MISSING = "build_tool_missing"
    PERMISSION_ERROR = "permission_error"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ProjectInfo:
    root: Path
    kind: ProjectKind
    name: str
    files: list[str] = field(default_factory=list)
    entry_point: str = ""
    dependency_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    run_hint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DevRunResult:
    success: bool
    root: Path
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    category: DevErrorCategory = DevErrorCategory.NONE
    message: str = ""
    duration_seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectPlan:
    name: str
    language: str
    framework: str = ""
    description: str = ""
    entry_point: str = ""
    files: list[dict[str, str]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    test_strategy: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "language": self.language,
            "framework": self.framework,
            "description": self.description,
            "entry_point": self.entry_point,
            "files": list(self.files),
            "dependencies": list(self.dependencies),
            "test_strategy": self.test_strategy,
        }
