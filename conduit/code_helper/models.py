from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

class ErrorCategory(StrEnum):
    NONE = "none"
    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"
    DEPENDENCY_MISSING = "dependency_missing"
    COMPILATION_ERROR = "compilation_error"
    RUNTIME_ERROR = "runtime_error"
    TYPE_ERROR = "type_error"
    ASSERTION_FAILURE = "assertion_failure"
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    PERMISSION_ERROR = "permission_error"
    FILE_NOT_FOUND = "file_not_found"
    RUNTIME_MISSING = "runtime_missing"
    UNKNOWN = "unknown"

@dataclass(slots=True)
class CodeRunResult:
    success: bool
    language: str
    path: Path
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    category: ErrorCategory = ErrorCategory.NONE
    message: str = ""
    duration_seconds: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
