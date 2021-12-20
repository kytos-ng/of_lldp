"""Utils module."""

from .settings import COOKIE_PREFIX


def int_dpid(dpid):
    """Convert a str dpid to an int."""
    dpid = int(dpid.replace(":", ""), 16)
    return dpid


def get_cookie(dpid):
    """Return the cookie integer given a dpid."""
    return (0x0000FFFFFFFFFFFF & int(int_dpid(dpid))) | (COOKIE_PREFIX << 56)
