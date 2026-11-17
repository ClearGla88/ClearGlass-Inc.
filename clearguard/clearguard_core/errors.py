"""Exit codes and exception types."""

from __future__ import annotations

EXIT_OK = 0
EXIT_NOT_READY = 1  # completed, but readiness failures or findings remain
EXIT_ERROR = 2  # usage, unreadable input, invalid configuration
EXIT_INTEGRITY = 3  # signature or audit-chain verification failed


class ClearGuardError(Exception):
    """Operational error with a message safe to show the user."""


class ConfigError(ClearGuardError):
    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems) or "invalid configuration")


class IntegrityError(ClearGuardError):
    """A signature, key, or hash chain did not verify."""
