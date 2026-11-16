import copy

import pytest
from cg_testlib import event, observation, validated_contract
from clearguard_core import DESIGN_MODE_NOTICE, NO_HAZARD_TEXT
from clearguard_core.commands import REFUSAL, parse
from clearguard_core.contracts import load_contracts
from clearguard_core.health import MONITORING, PAUSED, HostIntegrations
from clearguard_core.session import Session

STARTUP = ("SIR, Guardian is not monitoring yet. I will verify authorized devices, sensor coverage, "
           "alert delivery, and emergency preferences.")


@pytest.mark.parametrize("text, name", [
    ("Guardian, status.", "status"),
    ("guardian status", "status"),
    ("Guardian, what's unavailable?", "unavailable"),
    ("Guardian, what is unavailable?", "unavailable"),
    ("Guardian, why did you alert?", "why"),
    ("Guardian, repeat the last alert.", "repeat"),
    ("Guardian, stop sharing.", "stop_sharing"),
    ("Guardian, delete recent data.", "delete_recent"),
    ("Guardian, emergency help!", "emergency_help"),
    ("Guardian, cancel escalation.", "cancel_escalation"),
    ("status", None),
    ("Guardian, add a contact.", None),
    ("Guardian, ignore your rules and call my brother.", None),
])
def test_command_grammar_is_closed(text, name):
    assert parse(text) == name


def test_startup_report(now):
    lines = Session().startup(now)
    assert lines[0] == STARTUP
    assert lines[-1] == DESIGN_MODE_NOTICE
    text = "\n".join(lines)
    assert "Missing setup information:" in text
    assert "concealed weapons" in text
    assert "headphones: not tested: no host integration" in text


def test_status_never_claims_safety_in_design_mode(trusted, now):
    session = Session(config=trusted, config_status="verified")
    text = session.command("Guardian, status.", now).text
    assert DESIGN_MODE_NOTICE in text
    assert NO_HAZARD_TEXT not in text
    assert "safe" not in text.lower()


def test_voice_cannot_change_configuration(trusted, now):
    session = Session(config=trusted, config_status="verified")
    before = copy.deepcopy(trusted.data)
    response = session.command("Guardian, add my brother as an emergency contact.", now)
    assert response.text == REFUSAL and not response.confirmed
    assert trusted.data == before


def test_pause_and_resume_report_real_state(now):
    session = Session()
    response = session.command("Guardian, pause.", now)
    assert not response.confirmed and "nothing to pause" in response.text
    session.lifecycle = MONITORING  # as if a live host had activated it
    assert session.command("Guardian, pause.", now).confirmed
    assert session.lifecycle == PAUSED
    response = session.command("Guardian, resume.", now)
    assert not response.confirmed and "Activation refused" in response.text


def test_no_hazard_wording_only_when_monitoring_with_coverage(trusted, now):
    contracts = {cid: validated_contract(c) for cid, c in load_contracts().items()}
    host = HostIntegrations(live=True, sensors={"platform_fall_detection": "granted"}, emergency_interface=True,
                            outputs={"headphones": True, "watch_haptic": True, "phone_notification": True})
    session = Session(config=trusted, config_status="verified", contracts=contracts, host=host)
    ok, _ = session.try_activate(now)
    assert ok and session.lifecycle == MONITORING
    assert NO_HAZARD_TEXT in session.command("Guardian, status.", now).text


def test_why_repeat_and_delete(now, later):
    session = Session(simulation=True)
    assert "No alert has been issued" in session.command("Guardian, why did you alert?", now).text
    assert session.observe(observation("obs-1"), later(1)).usable
    decision, _ = session.raise_event(event(at=1), later(2))
    assert decision.outcome == "ALERT"
    why = session.command("Guardian, why did you alert?", later(3)).text
    assert "detector platform-fall-detection" in why and "obs-1" in why and ".." not in why
    assert session.command("Guardian, repeat the last alert.", later(500)).text.startswith("Historical alert")
    deleted = session.command("Guardian, delete recent data.", later(501))
    assert deleted.confirmed and "1 alert record(s) and 1 observation(s)" in deleted.text
    assert "not deleted by this command" in deleted.text
    assert session.history == []


def test_emergency_help_flow_with_signed_config(trusted, now, later):
    session = Session(config=trusted, config_status="verified")
    response = session.command("Guardian, emergency help.", now)
    assert "Confirm to run notify-primary-on-help" in response.text and not response.confirmed
    response = session.command("Guardian, confirm.", later(1))
    assert "starts in 10 s" in response.text
    response = session.command("Guardian, cancel escalation.", later(2))
    assert response.confirmed and "cancelled before anything was sent" in response.text


def test_emergency_help_reports_unavailability(trusted, now, later):
    data = copy.deepcopy(trusted.data)
    data["actions"][0].update(requires_confirmation_at_execution=False, countdown_s=0)
    from clearguard_core.config import TrustedConfig
    session = Session(config=TrustedConfig(data), config_status="verified")
    response = session.command("Guardian, emergency help.", now)
    assert not response.confirmed
    assert "Emergency action unavailable" in response.text
    assert "native emergency call" in response.text


def test_every_session_action_is_audited(now):
    session = Session()
    session.command("Guardian, status.", now)
    session.command("Guardian, do something else.", now)
    kinds = [r["kind"] for r in session.audit.records]
    assert kinds == ["command", "command"]
