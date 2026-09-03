"""Browser-engine exceptions."""

class BrowserEngineError(RuntimeError):
    """Base error for managed browser automation."""


class BrowserNotStartedError(BrowserEngineError):
    """Raised when an operation requires an active browser session."""


class BrowserTargetError(BrowserEngineError):
    """Raised when a semantic element target cannot be resolved."""
