"""Test LivenessManager."""
# pylint: disable=invalid-name,protected-access
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from kytos.core.common import EntityStatus
from napps.kytos.of_lldp.managers.liveness import ILSM, LSM


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
        assert str(ilsm) == "ILSM(init, None)"

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

    """Test LSM."""

    def test_rpr(self, lsm) -> None:
        """Test repr."""
        assert str(lsm) == f"LSM(init, {str(lsm.ilsm_a)}, {str(lsm.ilsm_b)})"

    @pytest.mark.parametrize(
        "ilsm_a_state,ilsm_b_state,expected",
        [
            ("init", "dontcare", "init"),
            ("dontcare", "init", "init"),
            ("down", "dontcare", "down"),
            ("dontcare", "down", "down"),
            ("up", "init", "init"),
            ("init", "up", "init"),
            ("up", "up", "up"),
        ],
    )
    def test_agg_state(
        self, ilsm_a_state, ilsm_b_state, expected, lsm
    ) -> None:
        """Test aggregated state."""
        lsm.ilsm_a.state, lsm.ilsm_b.state = ilsm_a_state, ilsm_b_state
        assert lsm.agg_state() == expected

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
    def test_lsm_transitions(self, from_state, to) -> None:
        """Test LSM transitions."""
        lsm = LSM(ILSM(from_state), ILSM(from_state), from_state)
        assert lsm._transition_to(to) == to
        assert lsm.state == to

    def test_next_state(self, lsm) -> None:
        """Test next_state."""
        lsm.ilsm_a.transition_to("up")
        lsm.ilsm_b.transition_to("up")
        assert lsm.next_state() == "up"
        assert lsm.state == "up"

        assert not lsm.next_state()
        assert lsm.state == "up"

        lsm.ilsm_a.transition_to("down")
        assert lsm.next_state() == "down"
        assert lsm.state == "down"

        assert not lsm.next_state()
        assert lsm.state == "down"


class TestLivenessManager:

    """TestLivenessManager."""

    def test_is_enabled(self, liveness_manager, intf_one) -> None:
        """Test is_enabled."""
        assert not liveness_manager.interfaces
        assert not liveness_manager.is_enabled(intf_one)
        liveness_manager.interfaces[intf_one.id] = intf_one
        assert liveness_manager.is_enabled(intf_one)

    def test_enable(self, liveness_manager, intf_one, intf_two) -> None:
        """Test enable."""
        assert not liveness_manager.interfaces
        liveness_manager.enable(intf_one, intf_two)
        assert intf_one.id in liveness_manager.interfaces
        assert intf_two.id in liveness_manager.interfaces

    def test_disable(self, liveness_manager, intf_one, intf_two) -> None:
        """Test disable."""
        assert not liveness_manager.interfaces
        liveness_manager.enable(intf_one, intf_two)
        assert intf_one.id in liveness_manager.interfaces
        liveness_manager.disable(intf_one, intf_two)
        assert intf_one.id not in liveness_manager.interfaces

    def test_link_status_hook_liveness(self, liveness_manager) -> None:
        """Test link_status_hook_liveness."""
        mock_link = MagicMock()
        mock_link.is_active.return_value = True
        mock_link.is_enabled.return_value = True
        mock_link.metadata = {"liveness_status": "down"}
        status = liveness_manager.link_status_hook_liveness(mock_link)
        assert status == EntityStatus.DOWN

        mock_link.metadata = {"liveness_status": "up"}
        status = liveness_manager.link_status_hook_liveness(mock_link)
        assert status is None

    def test_try_to_publish_lsm_event(
        self, liveness_manager, intf_one, intf_two
    ) -> None:
        """Test try_to_publish_lsm_event."""
        event_suffix = None
        liveness_manager.try_to_publish_lsm_event(
            event_suffix, intf_one, intf_two
        )
        assert liveness_manager.controller.buffers.app.put.call_count == 0
        event_suffix = "up"
        liveness_manager.try_to_publish_lsm_event(
            event_suffix, intf_one, intf_two
        )
        assert liveness_manager.controller.buffers.app.put.call_count == 1

    async def test_atry_to_publish_lsm_event(
        self, liveness_manager, intf_one, intf_two
    ) -> None:
        """Test atry_to_publish_lsm_event."""
        liveness_manager.controller.buffers.app.aput = AsyncMock()
        event_suffix = None
        await liveness_manager.atry_to_publish_lsm_event(
            event_suffix, intf_one, intf_two
        )
        assert liveness_manager.controller.buffers.app.aput.call_count == 0
        event_suffix = "up"
        await liveness_manager.atry_to_publish_lsm_event(
            event_suffix, intf_one, intf_two
        )
        assert liveness_manager.controller.buffers.app.aput.call_count == 1

    async def test_get_interface_status(
        self, liveness_manager, intf_one, intf_two
    ) -> None:
        """Test get_interface_status."""
        assert liveness_manager.get_interface_status(intf_one.id) == (
            None,
            None,
        )
        liveness_manager.enable(intf_one, intf_two)
        assert liveness_manager.get_interface_status(intf_one.id) == (
            "init",
            None,
        )
        received_at = datetime.utcnow()
        await liveness_manager.consume_hello(intf_one, intf_two, received_at)
        assert liveness_manager.get_interface_status(intf_one.id) == (
            "up",
            received_at,
        )

    async def test_consume_hello(
        self, liveness_manager, intf_one, intf_two
    ) -> None:
        """Test consume_hello."""
        assert not liveness_manager.liveness
        received_at = datetime.utcnow()
        liveness_manager.atry_to_publish_lsm_event = AsyncMock()

        await liveness_manager.consume_hello(intf_one, intf_two, received_at)
        assert intf_one.id in liveness_manager.liveness
        assert intf_two.id not in liveness_manager.liveness
        entry = liveness_manager.liveness[intf_one.id]
        assert entry["interface_a"] == intf_one
        assert entry["interface_b"] == intf_two
        assert entry["lsm"].ilsm_a.state == "up"
        assert entry["lsm"].ilsm_b.state == "init"
        assert entry["lsm"].state == "init"
        assert liveness_manager.atry_to_publish_lsm_event.call_count == 1

        received_at = datetime.utcnow()
        await liveness_manager.consume_hello(intf_two, intf_one, received_at)
        assert entry["lsm"].ilsm_a.state == "up"
        assert entry["lsm"].ilsm_b.state == "up"
        assert entry["lsm"].state == "up"
        assert liveness_manager.atry_to_publish_lsm_event.call_count == 2

    async def test_consume_hello_reinit(
        self, liveness_manager, intf_one, intf_two, intf_three
    ) -> None:
        """Test consume_hello reinitialization, this test a corner
        case where one end of the link has a new interface."""
        assert not liveness_manager.liveness
        received_at = datetime.utcnow()
        liveness_manager.atry_to_publish_lsm_event = AsyncMock()

        await liveness_manager.consume_hello(intf_one, intf_two, received_at)
        await liveness_manager.consume_hello(intf_two, intf_one, received_at)
        assert intf_one.id in liveness_manager.liveness
        entry = liveness_manager.liveness[intf_one.id]
        assert entry["interface_a"] == intf_one
        assert entry["interface_b"] == intf_two
        assert entry["lsm"].ilsm_a.state == "up"
        assert entry["lsm"].ilsm_b.state == "up"
        assert entry["lsm"].state == "up"
        assert liveness_manager.atry_to_publish_lsm_event.call_count == 2

        await liveness_manager.consume_hello(intf_one, intf_three, received_at)
        entry = liveness_manager.liveness[intf_one.id]
        assert entry["lsm"].ilsm_a.state == "up"
        assert entry["lsm"].ilsm_b.state == "init"
        assert entry["lsm"].state == "init"
        assert liveness_manager.atry_to_publish_lsm_event.call_count == 3

    def test_should_call_reaper(self, liveness_manager, intf_one) -> None:
        """Test should call reaper."""
        intf_one.switch.is_connected = lambda: True
        intf_one.lldp = True
        liveness_manager.enable(intf_one)
        assert liveness_manager.should_call_reaper(intf_one)

        intf_one.lldp = False
        assert not liveness_manager.should_call_reaper(intf_one)
        intf_one.lldp = True
        assert liveness_manager.should_call_reaper(intf_one)

        liveness_manager.disable(intf_one)
        assert not liveness_manager.should_call_reaper(intf_one)
        liveness_manager.enable(intf_one)
        assert liveness_manager.should_call_reaper(intf_one)

        intf_one.switch.is_connected = lambda: False
        assert not liveness_manager.should_call_reaper(intf_one)
        intf_one.switch.is_connected = lambda: True
        assert liveness_manager.should_call_reaper(intf_one)

    def test_reaper(self, liveness_manager, lsm, intf_one, intf_two) -> None:
        """Test reaper."""
        intf_one.status, intf_two.status = EntityStatus.UP, EntityStatus.UP
        liveness_manager.liveness = {
            intf_one.id: {
                "interface_a": intf_one,
                "interface_b": intf_two,
                "lsm": lsm,
            }
        }
        liveness_manager.should_call_reaper = MagicMock(return_value=True)
        liveness_manager.try_to_publish_lsm_event = MagicMock()
        lsm.ilsm_a.reaper_check = MagicMock()
        lsm.ilsm_b.reaper_check = MagicMock()

        dead_interval = 3
        liveness_manager.reaper(dead_interval)

        lsm.ilsm_a.reaper_check.assert_called_with(dead_interval)
        lsm.ilsm_b.reaper_check.assert_called_with(dead_interval)
        assert liveness_manager.try_to_publish_lsm_event.call_count == 1

    async def test_consume_hello_if_enabled(self, liveness_manager) -> None:
        """Test test_consume_hello_if_enabled."""
        liveness_manager.is_enabled = MagicMock(return_value=True)
        liveness_manager.consume_hello = AsyncMock()
        await liveness_manager.consume_hello_if_enabled(
            MagicMock(), MagicMock()
        )
        assert liveness_manager.consume_hello.call_count == 1

        liveness_manager.is_enabled = MagicMock(return_value=False)
        await liveness_manager.consume_hello_if_enabled(
            MagicMock(), MagicMock()
        )
        assert liveness_manager.consume_hello.call_count == 1
