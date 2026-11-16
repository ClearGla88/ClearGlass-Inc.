import pytest
from clearguard_core.alerts import (
    ACCEPTED_BY_PLATFORM,
    EXPIRED,
    FAILED,
    PLAYBACK_COMPLETED,
    PLAYBACK_STARTED,
    QUEUED,
    TEMPLATES,
    AlertController,
    Delivery,
    UnavailableChannel,
    build_alert,
    lint_templates,
    template_problems,
)


class FakeChannel:
    def __init__(self, name, *, works=True, verified=True):
        self.name, self.works, self.verified = name, works, verified

    def submit(self, alert, delivery, now):
        delivery.advance(QUEUED, now)
        if self.works:
            delivery.advance(ACCEPTED_BY_PLATFORM, now, "test platform")
        else:
            delivery.advance(FAILED, now, "route lost")


def alert(now, later, ttl=60):
    return build_alert("obstacle_ahead", "e1", "camera-obstacle", now, later(ttl), simulated=False)


def test_all_templates_pass_the_lint():
    assert lint_templates() == []
    assert TEMPLATES["obstacle_ahead"][1] == "Obstacle ahead. Check your path."


@pytest.mark.parametrize("text, problem", [
    ("You are safe.", "banned phrase"),
    ("Safe to cross now, go ahead.", "banned phrase"),
    ("Run to the left immediately.", "banned phrase"),
    ("Attacker approaching from behind you.", "banned phrase"),
    ("Stop.", "words"),
    ("This message is far too long to be an urgent first alert for anyone.", "words"),
])
def test_template_rules(text, problem):
    assert any(problem in p for p in template_problems("t", text))


def test_delivery_states_and_wording(now):
    d = Delivery("A1", "headphones")
    with pytest.raises(ValueError):
        d.advance(PLAYBACK_COMPLETED, now)
    for state in (QUEUED, ACCEPTED_BY_PLATFORM, PLAYBACK_STARTED, PLAYBACK_COMPLETED):
        d.advance(state, now)
    assert "does not confirm it was heard" in d.describe()


def test_no_verified_channel_means_failed(now, later):
    controller = AlertController([UnavailableChannel("headphones"), UnavailableChannel("watch_haptic")])
    [d] = controller.dispatch(alert(now, later), now)
    assert d.state == FAILED and "no verified alert channel" in d.describe()


def test_fallback_uses_only_verified_channels(now, later):
    controller = AlertController([
        FakeChannel("headphones", works=False),
        FakeChannel("watch_haptic", verified=False),
        FakeChannel("phone_notification"),
    ])
    deliveries = controller.dispatch(alert(now, later), now)
    assert [(d.channel, d.state) for d in deliveries] == [
        ("headphones", FAILED), ("phone_notification", ACCEPTED_BY_PLATFORM),
    ]


def test_expired_alerts_are_not_dispatched_and_replays_are_marked(now, later):
    a = alert(now, later, ttl=5)
    controller = AlertController([FakeChannel("headphones")])
    [d] = controller.dispatch(a, later(10))
    assert d.state == EXPIRED
    assert a.replay_text(later(1)) == "Obstacle ahead. Check your path."
    assert a.replay_text(later(10)).startswith("Historical alert from 15:00:00 UTC, no longer current:")


def test_headphone_loss_message_claims_only_verified_fallbacks():
    assert AlertController([FakeChannel("watch_haptic")]).headphone_loss_template() == "headphones_lost_watch"
    assert AlertController([FakeChannel("watch_haptic", verified=False), FakeChannel("phone_notification")]) \
        .headphone_loss_template() == "headphones_lost_phone"
    assert AlertController([UnavailableChannel("watch_haptic")]).headphone_loss_template() == "headphones_lost_none"
