import pytest

from guardian_core.errors import TransitionError
from guardian_core.states import (ACTION_TRANSITIONS, DELIVERY_TRANSITIONS, LIFECYCLE_TRANSITIONS,
                                  ActionOutcome, DeliveryState, Lifecycle, check_transition)


@pytest.mark.parametrize("table,enum", [(LIFECYCLE_TRANSITIONS, Lifecycle),
                                        (DELIVERY_TRANSITIONS, DeliveryState),
                                        (ACTION_TRANSITIONS, ActionOutcome)])
def test_every_state_has_a_row_and_unlisted_moves_are_refused(table, enum):
    assert set(table) == set(enum)
    for current in enum:
        for target in enum:
            if target in table[current]:
                check_transition(table, current, target)
            else:
                with pytest.raises(TransitionError):
                    check_transition(table, current, target)


def test_monitoring_is_reachable_only_from_ready_or_paused():
    sources = {s for s, targets in LIFECYCLE_TRANSITIONS.items() if Lifecycle.MONITORING in targets}
    assert sources == {Lifecycle.READY, Lifecycle.PAUSED}


def test_playback_completion_is_not_acknowledgement():
    assert DeliveryState.PLAYBACK_COMPLETED in DELIVERY_TRANSITIONS[DeliveryState.PLAYBACK_STARTED]
    for terminal in (DeliveryState.USER_ACKNOWLEDGED, DeliveryState.FAILED, DeliveryState.EXPIRED):
        assert DELIVERY_TRANSITIONS[terminal] == frozenset()


def test_nothing_attempted_can_be_cancelled():
    for state in (ActionOutcome.ATTEMPTED, ActionOutcome.CONNECTED, ActionOutcome.SENT, ActionOutcome.DELIVERED):
        assert ActionOutcome.CANCELLED not in ACTION_TRANSITIONS[state]
