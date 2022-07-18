"""Test LoopManager methods."""
from datetime import timedelta
from unittest import TestCase
from unittest.mock import MagicMock, patch

from kytos.lib.helpers import get_interface_mock, get_switch_mock

from kytos.core.helpers import now
from napps.kytos.of_lldp.loop_manager import LoopManager


class TestLoopManager(TestCase):
    """Tests for LoopManager."""

    def setUp(self):
        """Execute steps before each tests."""
        controller = MagicMock()
        self.loop_manager = LoopManager(controller)

    def test_is_looped(self):
        """Test is_looped cases."""

        dpid_a = "00:00:00:00:00:00:00:01"
        dpid_b = "00:00:00:00:00:00:00:02"
        values = [
            (dpid_a, 6, dpid_a, 7, True),
            (dpid_a, 1, dpid_a, 2, True),
            (dpid_a, 7, dpid_a, 7, True),
            (dpid_a, 8, dpid_a, 1, False),  # port_a > port_b
            (dpid_a, 1, dpid_b, 2, False),
            (dpid_a, 2, dpid_b, 1, False),
        ]
        for dpid_a, port_a, dpid_b, port_b, looped in values:
            with self.subTest(
                dpid_a=dpid_a, port_a=port_a, port_b=port_b, looped=looped
            ):
                assert (
                    self.loop_manager.is_looped(
                        dpid_a, port_a, dpid_b, port_b
                    )
                    == looped
                )

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

    @patch("napps.kytos.of_lldp.loop_manager.log")
    def test_handle_log_action(self, mock_log):
        """Test handle_log_action."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        self.loop_manager.handle_log_action(intf_a, intf_b)
        mock_log.warning.call_count = 1
        assert self.loop_manager.loop_counter[dpid][(1, 2)] == 0
        self.loop_manager.handle_log_action(intf_a, intf_b)
        mock_log.warning.call_count = 1
        assert self.loop_manager.loop_counter[dpid][(1, 2)] == 1

    @patch("napps.kytos.of_lldp.loop_manager.requests")
    @patch("napps.kytos.of_lldp.loop_manager.log")
    def test_handle_disable_action(self, mock_log, mock_requests):
        """Test handle_disable_action."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        response = MagicMock()
        response.status_code = 200
        mock_requests.post.return_value = response
        self.loop_manager.handle_disable_action(intf_a, intf_b)
        assert mock_requests.post.call_count == 1
        assert mock_log.info.call_count == 1

    @patch("napps.kytos.of_lldp.loop_manager.requests")
    @patch("napps.kytos.of_lldp.loop_manager.log")
    def test_handle_loop_stopped(self, mock_log, mock_requests):
        """Test handle_loop_stopped."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)

        self.loop_manager.loop_state[dpid][(1, 2)] = {"state": "detected"}
        self.loop_manager.actions = ["log", "disable"]
        mock_requests.post.return_value = MagicMock(status_code=200)
        mock_requests.delete.return_value = MagicMock(status_code=200)
        self.loop_manager.handle_loop_stopped(intf_a, intf_b)
        assert mock_requests.delete.call_count == 1
        assert mock_requests.post.call_count == 1
        assert "log" in self.loop_manager.actions
        assert "disable" in self.loop_manager.actions
        assert mock_log.info.call_count == 2
        assert self.loop_manager.loop_state[dpid][(1, 2)]["state"] == "stopped"

    @patch(
        "napps.kytos.of_lldp.loop_manager.LoopManager.add_interface_metadata"
    )
    def test_handle_loop_detected(self, mock_add_interface_metadata):
        """Test handle_loop_detected."""

        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)

        port_pair = (1, 2)
        self.loop_manager.handle_loop_detected(intf_a.id, dpid, port_pair)
        assert (
            self.loop_manager.loop_state[dpid][port_pair]["state"]
            == "detected"
        )
        assert mock_add_interface_metadata.call_count == 1

        # aditional call while is still active it shouldn't add metadata again
        self.loop_manager.handle_loop_detected(intf_a.id, dpid, port_pair)
        assert mock_add_interface_metadata.call_count == 1

        # force a different initial state to ensure it would overwrite
        self.loop_manager.loop_state[dpid][port_pair]["state"] = "stopped"
        self.loop_manager.handle_loop_detected(intf_a.id, dpid, port_pair)
        assert mock_add_interface_metadata.call_count == 2

    @patch("napps.kytos.of_lldp.loop_manager.requests")
    def test_add_interface_metadata(self, mock_requests):
        """Test add interface metadata."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        metadata = {
            "state": "looped",
            "port_numbers": [1, 2],
            "updated_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
            "detected_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        self.loop_manager.add_interface_metadata(intf_a.id, metadata)
        assert mock_requests.post.call_count == 1

    @patch("napps.kytos.of_lldp.loop_manager.requests")
    def test_del_interface_metadata(self, mock_requests):
        """Test del interface metadata."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        self.loop_manager.del_interface_metadata(intf_a.id, "looped")
        assert mock_requests.delete.call_count == 1

    def test_publish_loop_state(self):
        """Test publish_loop_state."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        state = "detected"

        self.loop_manager.publish_loop_state(intf_a, intf_b, state)
        assert self.loop_manager.controller.buffers.app.put.call_count == 1

    def test_publish_loop_actions(self):
        """Test publish_loop_actions."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        self.loop_manager.publish_loop_actions(intf_a, intf_b)
        assert self.loop_manager.controller.buffers.app.put.call_count == len(
            set(self.loop_manager.actions)
        )

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

    @patch("napps.kytos.of_lldp.loop_manager.LoopManager.publish_loop_state")
    @patch("napps.kytos.of_lldp.loop_manager.LoopManager.publish_loop_actions")
    def test_process_if_looped(self, mock_publish_actions, mock_publish_state):
        """Test process_if_looped."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        intf_a = get_interface_mock("s1-eth1", 1, switch)
        intf_b = get_interface_mock("s1-eth2", 2, switch)
        self.loop_manager.ignored_loops = {}
        assert self.loop_manager.process_if_looped(intf_a, intf_b)
        assert mock_publish_actions.call_count == 1
        assert mock_publish_state.call_count == 1

    def test_handle_topology_update(self):
        """Test handle_topology pudate."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        mock_topo = MagicMock()
        switch.metadata = {"ignored_loops": [[1, 2]]}
        mock_topo.switches = {dpid: switch}

        assert dpid not in self.loop_manager.ignored_loops
        self.loop_manager.handle_topology_loaded(mock_topo)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

    def test_handle_switch_metadata_changed_added(self):
        """Test handle_switch_metadata_changed added."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.metadata = {"ignored_loops": [[1, 2]]}

        assert dpid not in self.loop_manager.ignored_loops
        self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

    def test_handle_switch_metadata_changed_incrementally(self):
        """Test handle_switch_metadata_changed incrementally."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.id = dpid
        switch.metadata = {"ignored_loops": [[1, 2]]}
        self.loop_manager.ignored_loops = {}

        assert dpid not in self.loop_manager.ignored_loops
        self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2]]

        switch.metadata = {"ignored_loops": [[1, 2], [3, 4]]}
        self.loop_manager.handle_switch_metadata_changed(switch)
        assert self.loop_manager.ignored_loops[dpid] == [[1, 2], [3, 4]]

    def test_handle_switch_metadata_changed_removed(self):
        """Test handle_switch_metadata_changed removed."""
        dpid = "00:00:00:00:00:00:00:01"
        switch = get_switch_mock(dpid, 0x04)
        switch.id = dpid
        switch.metadata = {"some_key": "some_value"}
        self.loop_manager.ignored_loops[dpid] = [[1, 2]]

        assert dpid in self.loop_manager.ignored_loops
        self.loop_manager.handle_switch_metadata_changed(switch)
        assert dpid not in self.loop_manager.ignored_loops
