"""
Custom exception types for the backups project.

Phase 1 requires several configuration-related exceptions used by the
configuration loader and CLI.
"""

from __future__ import annotations


class ConfigError(Exception):
    """Base class for configuration-related errors."""

    pass


class ConfigSyntaxError(ConfigError):
    """Raised when YAML parsing fails due to syntax errors."""

    pass


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails (missing fields, invalid types, paths etc.)."""

    pass
