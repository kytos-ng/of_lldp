"""Test utils module."""
from unittest import TestCase

import pytest
from napps.kytos.of_lldp.utils import get_cookie, int_dpid, try_to_gen_intf_mac


@pytest.mark.parametrize(
    "address,dpid,port_number,expected",
    [
        (
            "00:00:00:00:00:00",
            "00:00:00:00:00:00:00:01",
            1,
            "0e:00:00:00:01:01",
        ),
        (
            "00:00:00:00:00:00",
            "00:00:01:22:03:04:05:06",
            1,
            "2e:03:04:05:06:01",
        ),
        (
            "00:00:00:00:00:00",
            "00:00:00:00:00:00:02:01",
            258,
            "0e:00:00:02:01:02",
        ),
        (
            "da:47:01:d8:03:44",
            "00:00:00:00:00:00:00:01",
            1,
            "da:47:01:d8:03:44",
        ),
        (
            "db:47:01:d8:03:44",
            "00:00:00:00:00:00:00:01",
            1,
            "0e:00:00:00:01:01"
        ),
        (
            "00:00:00:00:00:00",
            "00:" * 20,
            1,
            "00:00:00:00:00:00",
        ),
        (
            "00:00:00:00:00:00",
            "00:00:00:00:00:16:00:02",
            1,
            "0e:00:16:00:02:01",
        ),
    ],
)
def test_try_to_gen_intf_mac(address, dpid, port_number, expected) -> None:
    """Test try_to_gen_intf_mac."""
    assert try_to_gen_intf_mac(address, dpid, port_number) == expected


class TestUtils(TestCase):
    """Tests for the utils module."""

    def test_int_dpid(self):
        """Test int dpid."""
        test_data = [
            (
                "21:00:10:00:00:00:00:02",
                0x2100100000000002,
            ),
            (
                "00:00:00:00:00:00:00:07",
                0x0000000000000007,
            ),
        ]
        for dpid, expected_dpid in test_data:
            with self.subTest(dpid=dpid, expected_dpid=expected_dpid):
                assert int_dpid(dpid) == expected_dpid

    @staticmethod
    def test_get_cookie():
        """Test get_cookie."""
        dpid = "00:00:00:00:00:00:00:01"
        assert hex(get_cookie(dpid)) == hex(0xab00000000000001)
