"""Utils module."""

from functools import cache

from .settings import COOKIE_PREFIX


def int_dpid(dpid):
    """Convert a str dpid to an int."""
    dpid = int(dpid.replace(":", ""), 16)
    return dpid


def get_cookie(dpid):
    """Return the cookie integer given a dpid."""
    return (0x0000FFFFFFFFFFFF & int(int_dpid(dpid))) | (COOKIE_PREFIX << 56)


@cache
def try_to_gen_intf_mac(address: str, dpid: str, port_number: int) -> str:
    """Try to generate interface address if needed in a best effort way.

    This is a sanity check to ensure that the source interface will
    have a valid MAC, just so packets don't get potentially discarded.
    """
    if all((
        not _is_default_mac(address),
        not _has_mac_multicast_bit_set(address)
    )):
        return address

    dpid_split = dpid.split(":")
    if len(dpid_split) != 8:
        return address

    address = _gen_mac_address(dpid_split, port_number)
    address = _make_unicast_local_mac(address)
    return address


def _has_mac_multicast_bit_set(address: str) -> bool:
    """Check whether it has the multicast bit set or not."""
    try:
        return int(address[1], 16) & 1
    except (TypeError, ValueError, IndexError):
        return False


def _is_default_mac(address: str) -> bool:
    """Check whether is default mac or not."""
    return address == "00:00:00:00:00:00"


def _gen_mac_address(dpid_split: list[str], port_number: int) -> str:
    """Generate a MAC address deriving from dpid lsb 40 bits.
    A dpid is 8 bytes long: 16 bits + 48 bits.
    """
    port_number = port_number % (1 << 8)
    return ":".join(dpid_split[-5:] + [f"{port_number:02x}"])


def _make_unicast_local_mac(address: str) -> str:
    """
    Make an unicast locally administered address.

    The first two bits (b0, b1) of the most significant MAC address byte is for
    its uniqueness and wether its locally administered or not. This functions
    ensures it's a unicast (b0 -> 0) and locally administered (b1 -> 1).
    """
    return address[:1] + "e" + address[2:]
