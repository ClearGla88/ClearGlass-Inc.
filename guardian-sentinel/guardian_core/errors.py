"""Exception types. Every failure is explicit; nothing is silently ignored."""


class GuardianError(Exception):
    """Base class for every Guardian Sentinel error."""


class ConfigError(GuardianError):
    """The configuration is missing, unauthenticated or invalid."""


class TransitionError(GuardianError):
    """A state change that the state machine does not allow."""


class EvidenceError(GuardianError):
    """A capability promotion without the evidence its target state requires."""


class ObservationError(GuardianError):
    """A malformed observation."""


class HazardError(GuardianError):
    """A hazard event outside the supported categories or rules."""


class AuditError(GuardianError):
    """An audit record that is forbidden or a chain that does not verify."""
