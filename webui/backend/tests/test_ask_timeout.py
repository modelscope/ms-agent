"""Which permission modes bound the wait for an approval, and which do not."""
import pytest

from app.backends.ms_agent.runtime import (FULL_ACCESS_ASK_TIMEOUT_S,
                                           _ask_timeout_for)


@pytest.mark.parametrize("mode", ["ask", "restricted", "interactive", "", None])
def test_asking_modes_wait_indefinitely(mode):
    """Someone who chose to be consulted intends to answer. Expiring the
    question answers it for them, as a refusal they never gave and cannot
    undo."""
    assert _ask_timeout_for(mode) is None


@pytest.mark.parametrize(
    "mode", ["auto", "full", "full_access", "full-access", "strict", "AUTO"])
def test_full_access_bounds_the_wait(mode):
    """The opposite statement — nobody may be watching at all — so a session
    left running does not park on a question forever."""
    assert _ask_timeout_for(mode) == FULL_ACCESS_ASK_TIMEOUT_S


def test_the_bound_is_long_enough_to_step_away():
    # Short enough to matter, long enough to survive a meeting. A value in the
    # low minutes would recreate the problem it exists to solve.
    assert FULL_ACCESS_ASK_TIMEOUT_S >= 10 * 60


def test_unknown_modes_do_not_silently_get_a_deadline():
    assert _ask_timeout_for("something-new") is None
