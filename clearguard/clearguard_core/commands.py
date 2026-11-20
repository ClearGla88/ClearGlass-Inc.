"""Voice-command grammar (spec section 16).

A closed list. Anything else is refused, including attempts to change settings
or permissions by speaking: configuration changes only through a signed file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

COMMANDS = {
    "status": "status",
    "what is unavailable": "unavailable",
    "why did you alert": "why",
    "repeat the last alert": "repeat",
    "pause": "pause",
    "resume": "resume",
    "stop sharing": "stop_sharing",
    "delete recent data": "delete_recent",
    "emergency help": "emergency_help",
    "cancel escalation": "cancel_escalation",
    # Not in the spec's list; needed because an action can require confirmation at execution time.
    "confirm": "confirm",
}

REFUSAL = (
    "Not a supported command. Settings, contacts and permissions change only through "
    "the app's authenticated controls, never by voice."
)

_PREFIX = re.compile(r"^\s*(?:hey\s+)?guardian\s*[,:]?\s*", re.IGNORECASE)


def parse(text: str) -> str | None:
    """Return the command name, or None when the text is not an exact supported command."""
    if not isinstance(text, str):
        return None
    match = _PREFIX.match(text)
    if not match:
        return None
    rest = text[match.end():].strip().lower()
    rest = re.sub(r"[.!?]+$", "", rest).strip()
    rest = re.sub(r"\s+", " ", rest).replace("what's", "what is")
    return COMMANDS.get(rest)


@dataclass
class Response:
    command: str | None
    text: str
    confirmed: bool = False  # True only when the application confirmed an effect
