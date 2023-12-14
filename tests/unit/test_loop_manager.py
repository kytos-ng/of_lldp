"""Test LoopManager methods."""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import Response

from kytos.lib.helpers import get_interface_mock, get_switch_mock

from kytos.core.helpers import now
from napps.kytos.of_lldp.managers.loop_manager import LoopManager


class TestLoopManager:
    """Tests for LoopManager."""

    def setup_method(self):
        """Execute steps before each tests."""
        controller = MagicMock()
        self.loop_manager = LoopManager(controller)

    async def test_process_if_looped(self):
        """Test process_if_looped."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        self.loop_manager.ignored_loops = {}
        self.loop_manager.publish_loop_actions = AsyncMock()
        self.loop_manager.apublish_loop_state = AsyncMock()
        assert await self.loop_manager.process_if_looped(intf_a, intf_b)
        assert self.loop_manager.publish_loop_actions.call_count == 1
        assert self.loop_manager.apublish_loop_state.call_count == 1

    async def test_publish_loop_state(self):
        """Test publish_loop_state."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        state = "detected"
        self.loop_manager.controller.buffers.app.aput = AsyncMock()
        await self.loop_manager.apublish_loop_state(intf_a, intf_b, state)
        assert self.loop_manager.controller.buffers.app.aput.call_count == 1

    async def test_publish_loop_actions(self):
        """Test publish_loop_actions."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        self.loop_manager.controller.buffers.app.aput = AsyncMock()
        await self.loop_manager.publish_loop_actions(intf_a, intf_b)
        assert self.loop_manager.controller.buffers.app.aput.call_count == len(
            set(self.loop_manager.actions)
        )

    @pytest.mark.parametrize("dpid_a,port_a,dpid_b,port_b,expected", [
        ("00:00:00:00:00:00:00:01", 6, "00:00:00:00:00:00:00:01", 7, True),
        ("00:00:00:00:00:00:00:01", 1, "00:00:00:00:00:00:00:01", 2, True),
        ("00:00:00:00:00:00:00:01", 7, "00:00:00:00:00:00:00:01", 7, True),
        ("00:00:00:00:00:00:00:01", 8, "00:00:00:00:00:00:00:01", 1, False),
        ("00:00:00:00:00:00:00:01", 1, "00:00:00:00:00:00:00:02", 2, False),
        ("00:00:00:00:00:00:00:01", 2, "00:00:00:00:00:00:00:02", 1, False),
    ])
    def test_is_looped(self, dpid_a, port_a, dpid_b, port_b, expected):
        """Test is_looped cases."""
        assert self.loop_manager.is_looped(
            dpid_a, port_a, dpid_b, port_b
        ) == expected

    def test_is_loop_ignored(self):
        """Test is_loop_ignored."""

        dpid = "00:00:00:00:00:00:00:01"
        port_a = 1
        port_b = 2
        self.loop_manager.ignored_loops[dpid] = [[port_a, port_b]]

        assert self.loop_manager.is_loop_ignored(
            dpid, port_a=port_a, port_b=port_b
        )
        assert self.loop_manager.is_loop_ignored(
            dpid, port_a=port_b, port_b=port_a
        )

        assert not self.loop_manager.is_loop_ignored(
            dpid, port_a + 20, port_b
        )

        dpid = "00:00:00:00:00:00:00:02"
        assert not self.loop_manager.is_loop_ignored(dpid, port_a, port_b)

    @patch("napps.kytos.of_lldp.managers.loop_manager.log")
    async def test_handle_log_action(self, mock_log):
        """Test handle_log_action."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        await self.loop_manager.handle_log_action(intf_a, intf_b)
        mock_log.warning.call_count = 1
        assert self.loop_manager.loop_counter[dpid][(1, 2)] == 0
        await self.loop_manager.handle_log_action(intf_a, intf_b)
        mock_log.warning.call_count = 1
        assert self.loop_manager.loop_counter[dpid][(1, 2)] == 1

    @patch("napps.kytos.of_lldp.managers.loop_manager.log")
    async def test_handle_disable_action(self, mock_log, monkeypatch):
        """Test handle_disable_action."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        aclient_mock, awith_mock = AsyncMock(), MagicMock()
        aclient_mock.post.return_value = Response(200, json={},
                                                  request=MagicMock())
        awith_mock.return_value.__aenter__.return_value = aclient_mock
        monkeypatch.setattr("httpx.AsyncClient", awith_mock)

        await self.loop_manager.handle_disable_action(intf_a, intf_b)
        assert aclient_mock.post.call_count == 1
        assert mock_log.info.call_count == 1

    @patch("napps.kytos.of_lldp.managers.loop_manager.log")
    async def test_handle_loop_stopped(self, mock_log, monkeypatch):
        """Test handle_loop_stopped."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        aclient_mock, awith_mock = AsyncMock(), MagicMock()
        aclient_mock.post.return_value = Response(200, json={},
                                                  request=MagicMock())
        awith_mock.return_value.__aenter__.return_value = aclient_mock
        monkeypatch.setattr("httpx.AsyncClient", awith_mock)

        self.loop_manager.loop_state[dpid][(1, 2)] = {"state": "detected"}
        self.loop_manager.actions = ["log", "disable"]
        await self.loop_manager.handle_loop_stopped(intf_a, intf_b)
        assert intf_a.remove_metadata.call_count == 1
        intf_a.remove_metadata.assert_called_with("looped")
        assert "log" in self.loop_manager.actions
        assert "disable" in self.loop_manager.actions
        assert mock_log.info.call_count == 2
        assert self.loop_manager.loop_state[dpid][(1, 2)]["state"] == "stopped"

    async def test_set_loop_detected(self):
        """Test set_loop_detected."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        port_pair = [intf_a.port_number, intf_b.port_number]
        await self.loop_manager.set_loop_detected(intf_a, port_pair)
        assert intf_a.extend_metadata.call_count == 1

        tuple_pair = tuple(port_pair)
        loop_state = self.loop_manager.loop_state
        assert loop_state[dpid][tuple_pair]["state"] == "detected"
        detected_at = loop_state[dpid][tuple_pair]["detected_at"]
        assert detected_at
        updated_at = loop_state[dpid][tuple_pair]["updated_at"]
        assert updated_at

        # if it's called again updated_at should be udpated
        await self.loop_manager.set_loop_detected(intf_a, port_pair)
        assert intf_a.extend_metadata.call_count == 1
        assert loop_state[dpid][tuple_pair]["detected_at"] == detected_at
        assert loop_state[dpid][tuple_pair]["updated_at"] >= updated_at

        # force a different initial state to ensure it would overwrite
        self.loop_manager.loop_state[dpid][tuple_pair]["state"] = "stopped"
        await self.loop_manager.set_loop_detected(intf_a, port_pair)
        assert intf_a.extend_metadata.call_count == 2

    def test_get_stopped_loops(self):
        """Test get_stopped_loops."""
        dpid = "00:00:00:00:00:00:00:01"
        port_pairs = [(1, 2), (3, 3)]

        delta = now() - timedelta(minutes=1)
        looped_entry = {
            "state": "detected",
            "updated_at": delta.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        for port_pair in port_pairs:
            self.loop_manager.loop_state[dpid][port_pair] = looped_entry
        assert self.loop_manager.get_stopped_loops() == {dpid: port_pairs}

    async def test_handle_topology_loaded(self):
        """Test handle_topology loaded."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        mock_topo = MagicMock()
        switch.metadata = {"ignored_loops": [[1, 2]]}
        mock_topo.switches = {dpid: switch}

        self.loop_manager.ignored_loops = {}
        assert dpid not in self.loop_manager.ignored_loops
        await self.loop_manager.handle_topology_loaded(mock_topo)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

    async def test_handle_switch_metadata_changed_added(self):
        """Test handle_switch_metadata_changed added."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.metadata = {"ignored_loops": [[1, 2]]}

        self.loop_manager.ignored_loops = {}
        assert dpid not in self.loop_manager.ignored_loops
        await self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

    async def test_handle_switch_metadata_changed_incrementally(self):
        """Test handle_switch_metadata_changed incrementally."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.id = dpid
        switch.metadata = {"ignored_loops": [[1, 2]]}
        self.loop_manager.ignored_loops = {}

        assert dpid not in self.loop_manager.ignored_loops
        await self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

        switch.metadata = {"ignored_loops": [[1, 2], [3, 4]]}
        await self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2], [3, 4]]

    async def test_handle_switch_metadata_changed_removed(self):
        """Test handle_switch_metadata_changed removed."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.id = dpid
        switch.metadata = {"some_key": "some_value"}
        self.loop_manager.ignored_loops[dpid] = [[1, 2]]

        assert dpid in self.loop_manager.ignored_loops
        await self.loop_manager.handle_switch_metadata_changed(switch)
        assert dpid not in self.loop_manager.ignored_loops
