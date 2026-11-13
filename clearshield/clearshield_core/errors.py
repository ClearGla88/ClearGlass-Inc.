"""Exit codes and exception types.

Exit codes are part of the command-line contract (see README.md):

    0  completed, nothing to report
    1  completed, findings reported (changes, alerts, audio anomalies)
    2  operational error (usage, configuration, permissions, unreadable input)
    3  integrity failure (audit chain, state authentication, checkpoint mismatch)
"""

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2
EXIT_INTEGRITY = 3


class ClearShieldError(Exception):
    """Operational error. Message is shown to the operator; exit code 2."""

    exit_code = EXIT_ERROR


class ConfigError(ClearShieldError):
    """Missing or invalid configuration, or ClearShield not initialized."""


class InsecurePermissions(ClearShieldError):
    """State directory, key, or state file is readable or writable by others."""


class KeyFileError(ClearShieldError):
    """HMAC key missing, malformed, or not found for a record's key id."""


class AudioError(ClearShieldError):
    """WAV input is malformed, unsupported, or exceeds configured limits."""


class IntegrityFailure(ClearShieldError):
    """Authenticated data failed verification. Exit code 3."""

    exit_code = EXIT_INTEGRITY
