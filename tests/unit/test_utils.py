"""Test utils module."""
from unittest import TestCase

from napps.kytos.of_lldp.utils import get_cookie, int_dpid


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
        assert hex(get_cookie(dpid)) == hex(0xbb00000000000001)
