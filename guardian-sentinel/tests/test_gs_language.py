"""Every user-facing string, across many scenarios, avoids safety claims,
intent speculation and grade or certification language (SPEC sections 1, 8, 9)."""

from guardian_core.alerts import FORBIDDEN_PHRASES, TEMPLATES
from guardian_core.guardian import Guardian
from gs_testlib import NOW, FakeDispatcher
from test_gs_health_commands import monitoring_guardian

COMMANDS = ["status", "what is unavailable?", "why did you alert?", "repeat the last alert", "pause",
            "resume", "stop sharing", "delete recent data", "emergency help", "cancel escalation"]


def _all_text(g):
    out = [g.startup_report(NOW)]
    out += [g.command(f"Guardian, {c}", NOW + i).text for i, c in enumerate(COMMANDS)]
    return "\n".join(out).lower()


def test_no_forbidden_language_in_any_reply():
    for g in (Guardian(), monitoring_guardian(), monitoring_guardian(dispatcher=FakeDispatcher(["sent"] * 4))):
        text = _all_text(g)
        for phrase in FORBIDDEN_PHRASES:
            assert phrase not in text, phrase
        assert "you are safe" not in text


def test_templates_never_describe_people():
    for template in TEMPLATES.values():
        lowered = template.text.lower()
        assert not any(w in lowered for w in ("person", "stranger", "suspicious", "intent"))
