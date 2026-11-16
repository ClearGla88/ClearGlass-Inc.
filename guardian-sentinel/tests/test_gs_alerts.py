import pytest

from guardian_core.alerts import TEMPLATES, AlertController, headphone_loss_template, lint_message
from guardian_core.errors import HazardError, TransitionError
from guardian_core.hazards import make_event
from guardian_core.states import DeliveryState as D, Priority
from gs_testlib import NOW, FakeChannel, fall_event, help_event


def test_every_template_passes_the_language_lint():
    for tid, template in TEMPLATES.items():
        assert lint_message(template.text, template.priority) == [], tid


@pytest.mark.parametrize("text", ["You are safe.", "Safe to cross now.", "Threat ahead, run!",
                                  "Obstacle.", "One two three four five six seven eight nine ten eleven"])
def test_lint_catches_forbidden_or_badly_sized_messages(text):
    assert lint_message(text, Priority.CRITICAL)


def test_headphone_loss_claims_watch_fallback_only_when_verified():
    assert headphone_loss_template(True) == "headphones_disconnected_watch_verified"
    assert headphone_loss_template(False) == "headphones_disconnected_no_fallback"


def test_no_verified_channel_means_failed_not_delivered():
    ctrl = AlertController([FakeChannel(verified=None)])
    alert = ctrl.raise_alert(fall_event(), "possible_fall", NOW)
    assert alert.state is D.FAILED and alert.history[-1][2] == "no verified alert channel"


def test_falls_back_to_the_next_verified_channel():
    broken, refusing, watch = FakeChannel("hp", boom=True), FakeChannel("hp2", accept=False), FakeChannel("watch")
    alert = AlertController([broken, refusing, watch]).raise_alert(fall_event(), "possible_fall", NOW)
    assert alert.state is D.ACCEPTED_BY_PLATFORM and alert.channel == "watch"
    assert [h[0] for h in alert.history] == ["CREATED", "QUEUED", "CHANNEL_ERROR", "CHANNEL_REFUSED",
                                             "ACCEPTED_BY_PLATFORM"]


def test_delivery_states_follow_platform_reports_only():
    ctrl = AlertController([FakeChannel()])
    alert = ctrl.raise_alert(fall_event(), "possible_fall", NOW)
    ctrl.on_platform_event(alert.alert_id, D.PLAYBACK_STARTED, NOW + 1)
    ctrl.on_platform_event(alert.alert_id, D.PLAYBACK_COMPLETED, NOW + 3)
    assert alert.state is D.PLAYBACK_COMPLETED  # not USER_ACKNOWLEDGED
    with pytest.raises(TransitionError):
        ctrl.on_platform_event(alert.alert_id, D.QUEUED, NOW + 4)


def test_template_must_match_the_event_hazard():
    with pytest.raises(HazardError, match="does not describe"):
        AlertController([FakeChannel()]).raise_alert(fall_event(), "obstacle_ahead", NOW)
    with pytest.raises(HazardError, match="no approved template"):
        AlertController([FakeChannel()]).raise_alert(fall_event(), "free_text", NOW)


def test_duplicates_suppressed_inside_the_window_but_escalation_passes():
    ctrl = AlertController([FakeChannel()], dedupe_window_s=30)
    assert ctrl.raise_alert(fall_event("f1"), "possible_fall", NOW) is not None
    assert ctrl.raise_alert(fall_event("f2"), "possible_fall", NOW + 5) is None
    assert ctrl.suppressed == {("fall", "possible_fall"): 1}
    escalated = ctrl.raise_alert(fall_event("f3", priority="CRITICAL"), "possible_fall", NOW + 6)
    assert escalated is not None and escalated.priority is Priority.CRITICAL
    assert ctrl.raise_alert(fall_event("f4", created_at=NOW + 40), "possible_fall", NOW + 40) is not None


def test_no_window_means_no_suppression():
    ctrl = AlertController([FakeChannel()])
    assert all(ctrl.raise_alert(fall_event(f"f{i}"), "possible_fall", NOW) for i in range(3))


def test_stale_events_expire_and_are_repeated_only_as_history():
    ctrl = AlertController([FakeChannel()])
    late = ctrl.raise_alert(fall_event(created_at=NOW - 500), "possible_fall", NOW)
    assert late.state is D.EXPIRED
    ctrl2 = AlertController([FakeChannel()])
    ctrl2.raise_alert(fall_event(), "possible_fall", NOW)
    assert ctrl2.repeat_last(NOW + 10) == TEMPLATES["possible_fall"].text
    assert [a.alert_id for a in ctrl2.expire(NOW + 200)] == ["alert-1"]
    assert ctrl2.repeat_last(NOW + 200).startswith("Earlier alert, now expired:")


def test_user_originated_help_alert_uses_its_template():
    alert = AlertController([FakeChannel()]).raise_alert(help_event(), "help_request_received", NOW)
    assert alert.priority is Priority.CRITICAL


def test_obstacle_alert_requires_a_contract_for_an_obstacle_detector():
    from gs_testlib import contract
    obstacle = make_event(event_id="ob", hazard="obstacle", priority="CRITICAL", detector_id="cam",
                          created_at=NOW, max_age_s=2, observation_ids=("o",), observed_facts=("object in path",),
                          contract=contract(hazard="obstacle", alert_template_id="obstacle_ahead"))
    alert = AlertController([FakeChannel()]).raise_alert(obstacle, "obstacle_ahead", NOW)
    assert alert.text == "Obstacle ahead. Check your path."
