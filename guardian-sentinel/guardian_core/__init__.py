"""Guardian Sentinel: the deterministic core of a consent-based personal-safety
assistant, built in design mode.

This package provides no sensors, no detectors, no headphone output and no
emergency dispatch. It contains the parts of the specification (SPEC.md) that
can be implemented and tested without hardware: trusted configuration,
observation integrity checks, hazard events, the safety-policy rules, the
alert and emergency state machines, the health supervisor and the commands.
"""

__version__ = "0.1.0.dev0"

STARTUP_LINE = (
    "SIR, Guardian is not monitoring yet. I will verify authorized devices, "
    "sensor coverage, alert delivery, and emergency preferences."
)
DESIGN_MODE_STATEMENT = "Design mode only. No live monitoring or headphone alerting is active."
NO_HAZARD_STATEMENT = "No supported hazard detected in the available inputs."
