"""Conftest."""
import pytest

from napps.kytos.of_lldp.managers.liveness import ILSM
from napps.kytos.of_lldp.managers.liveness import LSM
from napps.kytos.of_lldp.managers.liveness import LivenessManager
from napps.kytos.of_lldp.controllers import LivenessController
from kytos.lib.helpers import get_switch_mock, get_interface_mock
from unittest.mock import MagicMock


@pytest.fixture
def ilsm() -> None:
    """ISLM fixture."""
    return ILSM()


@pytest.fixture
def lsm() -> None:
    """LSM fixture."""
    return LSM(ILSM(), ILSM())


@pytest.fixture
def switch_one():
    """Switch one fixture."""
    return get_switch_mock("00:00:00:00:00:00:00:01", 0x04)


@pytest.fixture
def switch_two():
    """Switch one fixture."""
    return get_switch_mock("00:00:00:00:00:00:00:02", 0x04)


@pytest.fixture
def intf_one(switch_one):
    """Interface one fixture."""
    return get_interface_mock("s1-eth1", 1, switch_one)


@pytest.fixture
def intf_two(switch_two):
    """Interface two fixture."""
    return get_interface_mock("s2-eth1", 1, switch_two)


@pytest.fixture
def intf_three(switch_two):
    """Interface three fixture."""
    return get_interface_mock("s2-eth2", 2, switch_two)


@pytest.fixture
def liveness_manager():
    """LivenessManager fixture."""
    return LivenessManager(MagicMock())


@pytest.fixture
def liveness_controller() -> None:
    """LivenessController."""
    return LivenessController(MagicMock())
