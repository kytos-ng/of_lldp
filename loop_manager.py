"""LoopManager."""
from collections import defaultdict
from enum import Enum
from threading import Lock

import requests

from kytos.core import KytosEvent, log
from kytos.core.helpers import get_time, now
from napps.kytos.of_lldp import settings as napp_settings


class LoopState(str, Enum):
    """LoopState Enum."""

    detected = "detected"
    stopped = "stopped"


class LoopManager:
    """LoopManager."""

    def __init__(self, controller, settings=napp_settings):
        """Constructor of LoopDetection."""
        self.controller = controller
        self.loop_lock = Lock()
        self.loop_counter = defaultdict(dict)
        self.loop_state = defaultdict(dict)

        self.settings = settings
        self.ignored_loops = settings.LLDP_IGNORED_LOOPS
        self.actions = settings.LLDP_LOOP_ACTIONS
        self.stopped_interval = 3 * settings.POLLING_TIME
        self.log_every = settings.LOOP_LOG_EVERY

    def is_loop_ignored(self, dpid, port_a, port_b):
        """Check if a loop is ignored."""
        if dpid not in self.ignored_loops:
            return False
        if any(
            (
                [port_a, port_b] in self.ignored_loops[dpid],
                [port_b, port_a] in self.ignored_loops[dpid],
            )
        ):
            return True
        return False

    @staticmethod
    def is_looped(dpid_a, port_a, dpid_b, port_b):
        """Check if the given dpids and ports are looped."""
        if all((dpid_a == dpid_b, port_a <= port_b)):  # only enter one pair
            return True
        return False

    def process_if_looped(
        self,
        interface_a,
        interface_b,
    ):
        """Process if interface_a and interface_b are looped."""
        dpid_a = interface_a.switch.dpid
        dpid_b = interface_b.switch.dpid
        port_a = interface_a.port_number
        port_b = interface_b.port_number
        if all(
            (
                self.is_looped(dpid_a, port_a, dpid_b, port_b),
                not self.is_loop_ignored(dpid_a, port_a, port_b),
            )
        ):
            self.publish_loop_state(
                interface_a, interface_b, LoopState.detected.value
            )
            self.publish_loop_actions(interface_a, interface_b)
            return True
        return False

    def publish_loop_state(
        self,
        interface_a,
        interface_b,
        state,
    ):
        """Publish loop state event."""
        dpid = interface_a.switch.dpid
        port_a = interface_a.port_number
        port_b = interface_b.port_number
        event = KytosEvent(
            name=f"kytos/of_lldp.loop.{state}",
            content={
                "interface_id": interface_a.id,
                "dpid": dpid,
                "port_numbers": [port_a, port_b],
            },
        )
        self.controller.buffers.app.put(event)

    def publish_loop_actions(
        self,
        interface_a,
        interface_b,
    ):
        """Publish loop action events."""
        supported_actions = {"log", "disable"}
        for action in set(self.actions).intersection(supported_actions):
            event = KytosEvent(
                name=f"kytos/of_lldp.loop.action.{action}",
                content={
                    "interface_a": interface_a,
                    "interface_b": interface_b,
                },
            )
            self.controller.buffers.app.put(event)

    def handle_loop_detected(self, interface_id, dpid, port_pair):
        """Handle loop detected."""
        is_new_loop = False
        port_pair = tuple(port_pair)
        with self.loop_lock:
            if port_pair not in self.loop_state[dpid]:
                dt_at = now().strftime("%Y-%m-%dT%H:%M:%S")
                data = {
                    "state": LoopState.detected.value,
                    "port_numbers": list(port_pair),
                    "updated_at": dt_at,
                    "detected_at": dt_at,
                }
                self.loop_state[dpid][port_pair] = data
                is_new_loop = True
            if (
                self.loop_state[dpid][port_pair]["state"]
                != LoopState.detected.value
            ):
                dt_at = now().strftime("%Y-%m-%dT%H:%M:%S")
                data = {
                    "state": LoopState.detected.value,
                    "updated_at": dt_at,
                    "detected_at": dt_at,
                }
                self.loop_state[dpid][port_pair].update(data)
                self.loop_state[dpid][port_pair].pop("stopped_at", None)
                is_new_loop = True
            else:
                data = {"updated_at": now().strftime("%Y-%m-%dT%H:%M:%S")}
                self.loop_state[dpid][port_pair].update(data)
        if is_new_loop:
            port_numbers = self.loop_state[dpid][port_pair]["port_numbers"]
            detected_at = self.loop_state[dpid][port_pair]["detected_at"]
            metadata = {
                "looped": {
                    "port_numbers": port_numbers,
                    "detected_at": detected_at,
                }
            }
            response = self.add_interface_metadata(interface_id, metadata)
            if response.status_code != 201:
                log.error(
                    f"Failed to add metadata {metadata} on interface "
                    f"{interface_id}, response: {response.json()}"
                )

    def has_loop_stopped(self, dpid, port_pair):
        """Check if a loop has stopped by checking within an interval
        or based on their operational state."""
        data = self.loop_state[dpid].get(port_pair)
        switch = self.controller.get_switch_by_dpid(dpid)
        if not data or not switch:
            return None
        try:
            interface_a = switch.interfaces[port_pair[0]]
            interface_b = switch.interfaces[port_pair[1]]
        except KeyError:
            return None

        if not interface_a.is_active() or not interface_b.is_active():
            return True

        delta_seconds = (now() - get_time(data["updated_at"])).seconds
        if delta_seconds > self.stopped_interval:
            return True
        return False

    def get_stopped_loops(self):
        """Get stopped loops."""
        stopped_loops = {}
        for key, state_dict in self.loop_state.items():
            for port_pair, values in state_dict.items():
                if values["state"] != LoopState.detected.value:
                    continue
                if self.has_loop_stopped(key, port_pair):
                    if key not in stopped_loops:
                        stopped_loops[key] = [port_pair]
                    else:
                        stopped_loops[key].append(port_pair)
        return stopped_loops

    def add_interface_metadata(self, interface_id, metadata):
        """Add interface metadata."""
        base_url = self.settings.TOPOLOGY_URL
        endpoint = f"{base_url}/interfaces/{interface_id}/metadata"
        return requests.post(endpoint, json=metadata)

    def del_interface_metadata(self, interface_id, key):
        """Delete interface metadata."""
        base_url = self.settings.TOPOLOGY_URL
        endpoint = f"{base_url}/interfaces/{interface_id}/metadata/{key}"
        return requests.delete(endpoint)

    def handle_loop_stopped(self, interface_a, interface_b):
        """Handle loop stopped."""
        dpid = interface_a.switch.dpid
        port_a = interface_a.port_number
        port_b = interface_b.port_number
        port_pair = (port_a, port_b)

        if port_pair not in self.loop_state[dpid]:
            return
        with self.loop_lock:
            dt_at = now().strftime("%Y-%m-%dT%H:%M:%S")
            data = {
                "state": "stopped",
                "updated_at": dt_at,
                "stopped_at": dt_at,
            }
            self.loop_state[dpid][port_pair].update(data)

        if "log" in self.actions:
            log.info(
                f"LLDP loop stopped on switch: {dpid}, "
                f"interfaces: {[interface_a.name, interface_b.name]}, "
                f"port_numbers: {[port_a, port_b]}"
            )
        if "disable" in self.actions:
            base_url = self.settings.TOPOLOGY_URL
            endpoint = f"{base_url}/interfaces/{interface_a.id}/enable"
            response = requests.post(endpoint)
            if response.status_code != 200:
                log.error(
                    f"Failed to enable interface: {interface_a.id},"
                    f" status code: {response.status_code}"
                )
            else:
                log.info(
                    "LLDP loop detection enabled interface "
                    f"{interface_a.id}, looped interfaces: "
                    f"{[interface_a.name, interface_b.name]},"
                    f"port_numbers: {[port_a, port_b]}"
                )

        key = "looped"
        response = self.del_interface_metadata(interface_a.id, key)
        if response.status_code != 200:
            log.error(
                f"Failed to delete metadata key {key} on interface ",
                f"{interface_a.id}",
            )

    def handle_log_action(
        self,
        interface_a,
        interface_b,
    ):
        """Execute loop log action."""
        dpid = interface_a.switch.dpid
        port_a = interface_a.port_number
        port_b = interface_b.port_number
        port_pair = (port_a, port_b)
        log_every = self.log_every
        with self.loop_lock:
            if port_pair not in self.loop_counter[dpid]:
                self.loop_counter[dpid][port_pair] = 0
            else:
                self.loop_counter[dpid][port_pair] += 1
                self.loop_counter[dpid][port_pair] %= log_every
            count = self.loop_counter[dpid][port_pair]
            if count != 0:
                return

        log.warning(
            f"LLDP loop detected on switch: {dpid}, "
            f"interfaces: {[interface_a.name, interface_b.name]}, "
            f"port_numbers: {[port_a, port_b]}"
        )

    def handle_disable_action(
        self,
        interface_a,
        interface_b,
    ):
        """Execute LLDP loop disable action idempotently."""
        if not interface_a.is_enabled():
            return

        port_a = interface_a.port_number
        port_b = interface_b.port_number
        intf_id = interface_a.id
        base_url = self.settings.TOPOLOGY_URL
        endpoint = f"{base_url}/interfaces/{intf_id}/disable"
        response = requests.post(endpoint)
        if response.status_code != 200:
            log.error(
                f"Failed to disable interface: {intf_id},"
                f" status code: {response.status_code}"
            )
            return

        log.info(
            f"LLDP loop detection disabled interface {interface_a.id}, "
            f"looped interfaces: {[interface_a.name, interface_b.name]}, "
            f"port_numbers: {[port_a, port_b]}"
        )

    def handle_switch_metadata_changed(self, switch):
        """Handle switch metadata changed."""
        if switch.id not in self.ignored_loops:
            self.try_to_load_ignored_switch(switch)
        else:
            with self.loop_lock:
                self.ignored_loops.pop(switch.dpid, None)

    def try_to_load_ignored_switch(self, switch):
        """Try to load an ignored switch."""
        if "ignored_loops" not in switch.metadata:
            return
        if not isinstance(switch.metadata["ignored_loops"], list):
            return

        dpid = switch.dpid
        with self.loop_lock:
            self.ignored_loops[dpid] = []
            for port_pair in switch.metadata["ignored_loops"]:
                if isinstance(port_pair, list):
                    self.ignored_loops[dpid].append(port_pair)

    def handle_topology_loaded(self, topology):
        """Handle on topology loaded."""
        for switch in topology.switches.values():
            self.try_to_load_ignored_switch(switch)
