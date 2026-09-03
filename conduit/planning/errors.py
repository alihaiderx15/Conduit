class PlanningError(RuntimeError):
    """Base planning failure."""


class PlanParseError(PlanningError):
    """Raised when provider output cannot be parsed into a plan."""


class PlanValidationError(PlanningError):
    """Raised when a parsed plan violates planner constraints."""
