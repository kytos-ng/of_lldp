"""Test LivenessManager."""
from datetime import datetime
from datetime import timedelta
import pytest

from napps.kytos.of_lldp.managers.liveness import ILSM


class TestILSM:

    """TestILSM."""

    @pytest.mark.parametrize(
        "from_state,to",
        [
            ("init", "up"),
            ("init", "down"),
            ("up", "down"),
            ("up", "init"),
            ("down", "up"),
            ("down", "init"),
        ],
    )
    def test_ilsm_transitions(self, from_state, to) -> None:
        """Test ILSM transitions."""
        ilsm = ILSM(state=from_state)
        assert ilsm.state == from_state
        assert ilsm.transition_to(to) == to
        assert ilsm.state == to

    def test_ilsm_invalid_transition(self) -> None:
        """Test ILSM invalid transition."""
        ilsm = ILSM(state="down")
        assert ilsm.state == "down"
        assert not ilsm.transition_to("down")
        assert not ilsm.transition_to("invalid_state")
        assert ilsm.state == "down"

    def test_repr(self, ilsm) -> None:
        """Test repr."""
        assert str(ilsm) == "ILSM(init, 1970-01-01 00:00:00)"

    def test_consume_hello(self, ilsm) -> None:
        """Test consume_hello."""
        assert ilsm.state == "init"
        received_at = datetime.utcnow()
        assert ilsm.consume_hello(received_at) == "up"
        assert ilsm.state == "up"
        assert ilsm.last_hello_at == received_at

    @pytest.mark.parametrize(
        "delta_secs, expected_state", [(0, "up"), (9, "up"), (10, "down")]
    )
    def test_reaper_check(self, ilsm, delta_secs, expected_state) -> None:
        """Test reaper_check."""
        assert ilsm.state == "init"
        dead_interval = 9
        delta = timedelta(seconds=delta_secs)
        received_at = datetime.utcnow() - delta
        ilsm.consume_hello(received_at)
        ilsm.reaper_check(dead_interval)
        assert ilsm.state == expected_state


class TestLSM:

    """Test LSM. """

    def test_rpr(self) -> None:
        """Test rpr."""
        pass


class TestLivenessManager:

    """TestLivenessManager."""

    pass
