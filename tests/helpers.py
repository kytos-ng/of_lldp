"""Module to help to create tests."""
from unittest.mock import MagicMock

from kytos.lib.helpers import (get_interface_mock, get_link_mock,
                               get_switch_mock)


def get_topology_mock():
    """Create a default topology."""
    switch_a = get_switch_mock("00:00:00:00:00:00:00:01", 0x04)
    switch_b = get_switch_mock("00:00:00:00:00:00:00:02", 0x04)

    interface_a1 = get_interface_mock("s1-eth1", 1, switch_a)
    interface_a2 = get_interface_mock("s1-eth2", 2, switch_a)

    interface_b1 = get_interface_mock("s2-eth1", 1, switch_b)
    interface_b2 = get_interface_mock("s2-eth2", 2, switch_b)

    switch_a.interfaces = {interface_a1.id: interface_a1,
                           interface_a2.id: interface_a2}
    switch_b.interfaces = {interface_b1.id: interface_b1,
                           interface_b2.id: interface_b2}

    link_1 = get_link_mock(interface_a1, interface_b1)

    topology = MagicMock()
    topology.links = {"1": link_1}
    topology.switches = {switch_a.dpid: switch_a,
                         switch_b.dpid: switch_b}
    return topology
