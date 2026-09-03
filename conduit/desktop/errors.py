"""Desktop-control specific exceptions."""


class DesktopControlError(Exception):
    """Base exception for desktop control failures."""


class CoordinateOutOfBoundsError(DesktopControlError):
    """Raised when a requested point is outside the virtual screen."""


class UnsupportedInputError(DesktopControlError):
    """Raised when a key or button value is unsupported."""
