"""LivenessManager."""
import logging

from typing import Optional
from datetime import datetime
from kytos.core.events import KytosEvent

# pylint: disable=invalid-name
log = logging.getLogger("kytos.napps.kytos/of_lldp")


class ILSM:

    """InterfaceLivenessStateMachine.

    This state machine represents the logical liveness state of the interface.
    If an interface is admin disabled or isn't active then a manager that uses
    this state machine should call the transition accordingly.
    """

    def __init__(self, state="init") -> None:
        """InterfaceLivenessStateMachine."""
        self.transitions = {
            "init": ["up", "down"],
            "up": ["down", "init"],
            "down": ["up", "init"],
        }
        self.state = state
        self.last_hello_at = datetime(year=1970, month=1, day=1)

    def __repr__(self) -> str:
        """Repr."""
        return f"ILSM({self.state}, {self.last_hello_at})"

    def transition_to(self, to_state: str) -> Optional[str]:
        """Try to transition to a state."""
        if to_state not in self.transitions[self.state]:
            return None
        self.state = to_state
        return self.state

    def reaper_check(self, dead_interval: int) -> Optional[str]:
        """Try to transition to down. It must be called every dead_interval."""
        if (datetime.utcnow() - self.last_hello_at).seconds > dead_interval:
            return self.transition_to("down")
        return None

    def consume_hello(self, received_at: datetime) -> Optional[str]:
        """Consume hello. It must be called on every received hello."""
        self.last_hello_at = received_at
        if self.transition_to("up"):
            return "up"
        return None


class LSM:

    """LivenessStateMachine aggregates two resulting ILSM acts like a link."""

    def __init__(self, ilsm_a: ILSM, ilsm_b: ILSM, state="init") -> None:
        """LinkLivenessStateMachine."""
        self.ilsm_a = ilsm_a
        self.ilsm_b = ilsm_b
        self.state = state
        self.transitions = self.ilsm_a.transitions

    def __repr__(self) -> str:
        """Repr."""
        return f"LSM({self.agg_state()}, {self.ilsm_a}, {self.ilsm_b})"

    def agg_state(self) -> str:
        """Aggregated state."""
        if self.ilsm_a.state == "init" or self.ilsm_b.state == "init":
            return "init"
        if self.ilsm_a.state == "down" or self.ilsm_b.state == "down":
            return "down"
        if self.ilsm_a.state == "up" and self.ilsm_b.state == "up":
            return "up"
        return "init"

    def _transition_to(self, to_state: str) -> Optional[str]:
        """Try to transition to a state."""
        if to_state not in self.transitions[self.state]:
            return None
        self.state = to_state
        return self.state

    def next_state(self) -> Optional[str]:
        """Next state."""
        return self._transition_to(self.agg_state())


class LivenessManager:

    """LivenessManager."""

    def __init__(self, controller) -> None:
        """LivenessManager."""

        self.controller = controller
        self.interfaces = {}
        # This dict is indexed by the lowest interface id of the pair.
        self.states = {}
        self.interfaces_idx = {}

    def is_enabled(self, *interfaces) -> bool:
        """Check if liveness is enabled on an interface."""
        for interface in interfaces:
            if interface.id not in self.interfaces:
                return False
        return True

    def enable(self, *interfaces):
        """Enable liveness on interface."""
        for interface in interfaces:
            self.interfaces[interface.id] = interface

    def disable(self, *interfaces):
        """Disable liveness interface."""
        for interface in interfaces:
            self.interfaces.pop(interface.id, None)

    async def atry_to_publish_lsm_event(
        self, event_suffix: str, interface_a, interface_b
    ) -> None:
        """Async try to publish a LSM event."""
        if not event_suffix:
            return
        name = f"kytos/of_lldp.liveness.{event_suffix}"
        content = {"interface_a": interface_a, "interface_b": interface_b}
        event = KytosEvent(name=name, content=content)
        await self.controller.buffers.app.aput(event)

    def try_to_publish_lsm_event(
        self, event_suffix: str, interface_a, interface_b
    ) -> None:
        """Try to publish a LSM event."""
        if not event_suffix:
            return
        name = f"kytos/of_lldp.liveness.{event_suffix}"
        content = {"interface_a": interface_a, "interface_b": interface_b}
        event = KytosEvent(name=name, content=content)
        self.controller.buffers.app.put(event)

    async def consume_hello(
        self, interface_a, interface_b, received_at: datetime
    ) -> None:
        """Consume liveness hello event."""
        min_id = min(interface_a.id, interface_b.id)
        is_interface_a_min_id = min_id == interface_a.id
        if min_id not in self.states:
            lsm = LSM(ILSM(state="init"), ILSM(state="init"))
            entry = {
                "lsm": lsm,
            }
            if is_interface_a_min_id:
                entry["interface_a"] = interface_a
                entry["interface_b"] = interface_b
            else:
                entry["interface_a"] = interface_b
                entry["interface_b"] = interface_a
            self.states[min_id] = entry
            self.interfaces_idx[interface_a.id] = min_id
            self.interfaces_idx[interface_b.id] = min_id

        entry = self.states[min_id]
        lsm = entry["lsm"]
        if is_interface_a_min_id:
            lsm.ilsm_a.consume_hello(received_at)
            if entry["interface_b"].id != interface_b.id:
                """
                Implies that the topology connection has changed, needs new ref
                """
                entry["interface_b"] = interface_b
                entry["lsm"].ilsm_b = ILSM(state="init")
        else:
            lsm.ilsm_b.consume_hello(received_at)

        lsm_next_state = lsm.next_state()
        log.debug(
            f"Liveness hello {interface_a.id} <- {interface_b.id}"
            f" next state: {lsm_next_state}, lsm: {lsm}"
        )
        await self.atry_to_publish_lsm_event(lsm_next_state, interface_a, interface_b)

    def should_process(self, interface) -> bool:
        """Should process."""
        if any(
            (
                not interface.switch.is_connected(),
                not interface.lldp,
                # TODO not feature enabled...
            )
        ):
            return False
        return True

    def reaper(self, dead_interval: int):
        """Reaper check processable interfaces."""
        # TODO do not send redundant notifications.. if it's already down, don't send.
        # TODO on topology if it's not active or disabled just ignore?
        for value in self.states.values():
            lsm, intf_a, intf_b = (
                value["lsm"],
                value["interface_a"],
                value["interface_b"],
            )
            if any(
                (
                    lsm.state == "down",
                    not self.should_process(intf_a),
                    not self.should_process(intf_b),
                )
            ):
                continue
            lsm.ilsm_a.reaper_check(dead_interval)
            lsm.ilsm_b.reaper_check(dead_interval)
            lsm_next_state = lsm.next_state()
            self.try_to_publish_lsm_event(
                lsm_next_state, value["interface_a"], value["interface_b"]
            )
