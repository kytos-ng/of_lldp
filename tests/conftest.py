"""Conftest."""
import pytest

from napps.kytos.of_lldp.managers.liveness import ILSM
from napps.kytos.of_lldp.managers.liveness import LSM


@pytest.fixture
def ilsm() -> None:
    """ISLM fixture."""
    return ILSM()

@pytest.fixture
def lsm() -> None:
    """LSM fixture."""
    return ILSM()
