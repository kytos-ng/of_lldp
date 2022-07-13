"""LivenessManager."""
import logging

from typing import Optional, Tuple
from datetime import datetime
from kytos.core.common import EntityStatus
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

        self.interfaces = {}  # liveness enabled
        self.liveness = {}  # indexed by the lowest interface id of the pair
        self.liveness_ids = {}  # interface id to lowest id of the pair

    def is_enabled(self, *interfaces) -> bool:
        """Check if liveness is enabled on an interface."""
        for interface in interfaces:
            if interface.id not in self.interfaces:
                return False
        return True

    def enable(self, *interfaces) -> None:
        """Enable liveness on interface."""
        for interface in interfaces:
            self.interfaces[interface.id] = interface

    def disable(self, *interfaces) -> None:
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

    async def consume_hello_if_enabled(self, interface_a, interface_b):
        """Consume liveness hello if enabled."""
        if not self.is_enabled(interface_a, interface_b):
            return
        await self.consume_hello(interface_a, interface_b, datetime.utcnow())

    def get_interface_status(
        self, interface_id
    ) -> Tuple[Optional[str], Optional[datetime]]:
        """Get interface status."""
        if interface_id not in self.interfaces:
            return None, None
        min_id = self.liveness_ids.get(interface_id)
        if min_id:
            lsm = self.liveness[min_id]["lsm"]
            if interface_id == min_id:
                return lsm.ilsm_a.state, lsm.ilsm_a.last_hello_at
            else:
                return lsm.ilsm_b.state, lsm.ilsm_b.last_hello_at
        return "init", None

    async def consume_hello(
        self, interface_a, interface_b, received_at: datetime
    ) -> None:
        """Consume liveness hello event."""
        min_id = min(interface_a.id, interface_b.id)
        is_interface_a_min_id = min_id == interface_a.id
        if min_id not in self.liveness:
            lsm = LSM(ILSM(state="init"), ILSM(state="init"))
            entry = {
                "lsm": lsm,
            }
            if is_interface_a_min_id:
                entry["interface_a"], entry["interface_b"] = interface_a, interface_b
            else:
                entry["interface_a"], entry["interface_b"] = interface_b, interface_a
            self.liveness[min_id] = entry
            self.liveness_ids[interface_a.id] = min_id
            self.liveness_ids[interface_b.id] = min_id

        entry = self.liveness[min_id]
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

    def should_call_reaper(self, interface) -> bool:
        """Should call reaper."""
        if all(
            (
                interface.switch.is_connected(),
                interface.lldp,
                self.is_enabled(interface),
            )
        ):
            return True
        return False

    def reaper(self, dead_interval: int):
        """Reaper check processable interfaces."""
        for value in self.liveness.values():
            lsm, intf_a, intf_b = (
                value["lsm"],
                value["interface_a"],
                value["interface_b"],
            )
            if any(
                (
                    lsm.state == "down",
                    not self.should_call_reaper(intf_a),
                    not self.should_call_reaper(intf_b),
                )
            ):
                continue

            lsm.ilsm_a.reaper_check(dead_interval)
            lsm.ilsm_b.reaper_check(dead_interval)
            lsm_next_state = lsm.next_state()

            if all(
                (
                    intf_a.status == EntityStatus.UP,
                    intf_b.status == EntityStatus.UP,
                )
            ):
                self.try_to_publish_lsm_event(
                    lsm_next_state, value["interface_a"], value["interface_b"]
                )
