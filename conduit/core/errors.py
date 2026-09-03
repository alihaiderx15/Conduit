"""Typed exceptions used throughout Conduit."""


class ConduitError(Exception):
    """Base exception for expected Conduit failures."""


class ProviderError(ConduitError):
    """Raised when an AI provider request fails."""


class ProviderConfigurationError(ProviderError):
    """Raised when provider configuration is missing or invalid."""


class ProviderUnavailableError(ProviderError):
    """Raised when a provider service cannot be reached."""


class UnsupportedCapabilityError(ProviderError):
    """Raised when a selected model/provider lacks a requested capability."""

class ProviderAuthenticationError(ProviderError):
    """Provider rejected credentials or the API key."""

class ProviderQuotaError(ProviderError):
    """Provider quota/rate limit/billing allowance is unavailable."""
